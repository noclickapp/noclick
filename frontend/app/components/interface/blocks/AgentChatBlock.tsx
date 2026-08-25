// Fullscreen chat interface for an agent node. Surfaces when the agent's config
// has `show_in_interface === "true"` — model picker in the header, transcript +
// chatbox on the left, a config sidebar on the right (system prompt,
// temperature, tools/triggers entry points). Subscribes to `useConversation`
// keyed on `ck:{wf}:{node}:{conversation_key}` (default key matches what
// FlowCanvas#handleAgentChatSend applies on send).

import { useCallback, useMemo, useRef, useState, useEffect } from 'react';
import { useSnapshot } from 'valtio';
import { FlaskConical, KeyRound, PanelRightClose, PanelRightOpen, Share } from 'lucide-react';
import { cn } from '~/lib/utils';
import { Switch } from '~/components/ui/switch';
import { AgentModelIcon } from '~/components/workflow/nodes/base/AgentModelIcon';
import { RehearsalScreen } from '~/components/design/rehearsal/RehearsalScreen';
import { useRehearsalIcons } from '~/components/design/rehearsal/useRehearsalIcons';
import {
    ReadinessCard,
    useWorkflowReadiness,
} from '~/components/workflow/setup/readiness';
import { useCachedValtioState } from '~/hooks/useCachedValtioState';
import { useValtioState } from '~/hooks/useValtioState';
import { useAgentChat, type BuilderPromptProposal } from '~/hooks/useAgentChat';
import { getAgentChatSession } from '~/lib/agentChatSessionStore';
import { sendEventAsync } from '~/lib/socket-sender';
import {
    agentPresenceStore,
    agentPresenceConversationKey,
} from '~/lib/agentPresenceStore';
import { useStickToBottom } from '~/hooks/useStickToBottom';
import {
    useAgentChatConversations,
    type AgentConversationSummary,
} from '~/hooks/useAgentChatConversations';
import { AgentCredentialsForm } from '~/components/workflow/AgentCredentialsForm';
import { AgentCredentialDialog } from './AgentCredentialDialog';
import { AgentShareDialog } from './AgentShareDialog';
import { AgentChatHistory } from './AgentChatHistory';
import {
    AgentSubModelPicker,
    getCliSubModelField,
} from './AgentSubModelPicker';
import { AgentChatTranscript } from '~/components/chat/AgentChatTranscript';
import { takeQueuedAgentChatSend } from '~/lib/pendingAgentSendStore';
import {
    WorkspaceFilePreviewDialog,
    WorkspaceFilesMenu,
    type WorkspacePreviewRequest,
} from '~/components/chat/WorkspaceFilesPanel';
import { useAgentWorkspaceFiles } from '~/hooks/useAgentWorkspaceFiles';
import { AgentChatComposer } from '~/components/chat/AgentChatComposer';
import type { BlockComponentProps } from '../types';
import { AgentModelPicker } from './AgentModelPicker';
import { AgentWiringSections } from './AgentWiringSections';
import {
    buildCarryOverContext,
    DEFAULT_AGENT_MODEL,
    DEFAULT_INTERFACE_CONV_KEY,
    deriveAgentChatConversationId,
    harnessOf,
    isImageAttachment,
    resolveRunModel,
    splitCarryOverContext,
    withCarriedContext,
} from '~/lib/agentChat';
import { useChatAttachments } from '~/hooks/useChatAttachments';
import {
    conversationNeedsFreshThread,
    getAgentEffectiveModel,
    staleCredentialKeysForProvider,
    inferProviderFromPrefix,
    validateAgentSendCredentials,
    seedWrapperSubmodel,
    WRAPPER_SUBMODEL_DEFAULT_BY_MODEL,
} from '~/lib/agentCredentialModel';
import { useModels } from '~/hooks/useModels';
import { ModelProvider } from '~/types/provider';

// Resizable settings sidebar bounds, in px. Kept at module scope so they
// aren't recreated on every render of the block.
const SIDEBAR_MIN = 240;
const SIDEBAR_MAX = 560;

// How long after a terminal frame the presence-driven working indicator stays
// suppressed — covers a delayed busy=false presence update.
const REMOTE_BUSY_GRACE_MS = 20_000;

export function AgentChatBlock({
    id,
    config,
    workflowId,
    onAgentChatSend,
    onConfigChange,
    isReadOnly,
    onInteraction,
    credentialIds,
    onCredentialIdsChange,
    agentWiring,
    onAgentWiringAdd,
    onAgentWiringRemove,
    onWiredNodeConfigPatch,
    onWiredNodeCredentialsChange,
    getWiredNodeData,
}: BlockComponentProps) {
    const currentConversationKey = config.conversation_key as
        | string
        | undefined;

    const conversationId = useMemo(
        () =>
            deriveAgentChatConversationId(
                workflowId,
                id,
                currentConversationKey
            ),
        [currentConversationKey, workflowId, id]
    );

    // conversation_key isn't eagerly written to the node config on mount —
    // FlowCanvas#handleAgentChatSend's run-override (and buildAgentChatConfigPatch's
    // persist patch) write it on the first send, which is also when the backend
    // first cares about persistence. Eager mount-time writes were redundant.

    const activeKey = currentConversationKey || DEFAULT_INTERFACE_CONV_KEY;

    // Conversation-scoped runtime presence from the workflow relay. Lights the
    // working indicator and keeps the hook's
    // reconciler polling for turns this tab never saw the send for — a reload
    // mid-turn, or a run started from a trigger / share page / another tab.
    const presenceBusy =
        !!useSnapshot(agentPresenceStore).byConversation[
            agentPresenceConversationKey(id, activeKey)
        ];

    const {
        messages,
        isStreaming,
        errorReason,
        addUserMessage,
        lastFinishedAt,
    } = useAgentChat(conversationId, undefined, presenceBusy);

    // File view for this conversation's persistent workspace volume (lazy —
    // listed on first open/preview, refreshed when a turn finishes).
    const workspaceFiles = useAgentWorkspaceFiles(
        workflowId,
        id,
        activeKey,
        lastFinishedAt
    );
    const [workspacePreview, setWorkspacePreview] =
        useState<WorkspacePreviewRequest | null>(null);
    const { refresh: refreshWorkspaceFiles, loaded: workspaceLoaded } =
        workspaceFiles;
    const openWorkspaceFile = useCallback(
        (path: string) => {
            // In-message link clicked before the panel was ever opened — load the
            // listing so the preview can resolve the path.
            if (!workspaceLoaded) void refreshWorkspaceFiles();
            setWorkspacePreview({ path });
        },
        [workspaceLoaded, refreshWorkspaceFiles]
    );

    // Persist approve/dismiss verdicts on builder proposal cards: restores the
    // card's decided state across devices AND relays the outcome to the agent
    // on its next turn (it otherwise only knows 'awaiting approval'). Fire-and-
    // forget — the card's localStorage fallback keeps local state either way.
    const handleBuilderDecision = useCallback(
        (
            proposal: BuilderPromptProposal,
            decision: 'approved' | 'dismissed'
        ) => {
            if (!workflowId || !conversationId || !proposal.proposal_id) return;
            void sendEventAsync({
                event_name: 'agent:builder_decision',
                workflow_id: workflowId,
                node_id: proposal.node_id ?? id,
                conversation_id: conversationId,
                proposal_id: proposal.proposal_id,
                decision,
            }).catch(() => {
                /* localStorage fallback holds the card state */
            });
        },
        [workflowId, conversationId, id]
    );

    // The busy beat can lag a finished turn by up to a heartbeat interval
    // (~15s); without this grace the dot would keep pulsing under a completed
    // answer. A turn genuinely started elsewhere clears the grace on the next
    // presence re-render. Raw presenceBusy still feeds the hook above — the
    // reconciler poll is idempotent and should keep running through the lag.
    const remoteBusy =
        presenceBusy && Date.now() - lastFinishedAt > REMOTE_BUSY_GRACE_MS;

    // Auto-scroll the transcript: stick to the bottom as messages arrive / stream,
    // unless the user has scrolled up to read history.
    const {
        ref: scrollRef,
        onScroll: onTranscriptScroll,
        pin: pinScroll,
    } = useStickToBottom([messages, isStreaming]);

    // Read selectedModel directly from config instead of mirroring it into local
    // state. The mirror introduced a stale-closure write path (handleModelSelect's
    // `config` snapshot could clobber a remote edit landing mid-flight).
    const selectedModel = (config.model as string) || DEFAULT_AGENT_MODEL;
    const [draft, setDraft] = useState('');
    const textareaRef = useRef<HTMLTextAreaElement>(null);
    // Synchronous re-entrancy guard for submit. `isStreaming` (set by addUserMessage)
    // is React state and doesn't flush before a same-tick second click, so two rapid
    // clicks (fast double-tap) both pass the isStreaming check and dispatch two runs,
    // surfaced later as "2 inputs consumed". This ref blocks
    // the second call synchronously; isStreaming owns the guard once React flushes.
    const submittingRef = useRef(false);

    const handleModelSelect = useCallback(
        (modelId: string) => {
            if (isReadOnly) return;
            // Seed a wrapper harness's default sub-model so the sub-model picker +
            // credential form resolve a concrete provider instead of the bare wrapper
            // id (no-op for regular models / already-set sub-models).
            onConfigChange({
                ...config,
                model: modelId,
                ...seedWrapperSubmodel(modelId, config),
            });
        },
        [config, isReadOnly, onConfigChange]
    );

    // Setter passed to useAgentChatConversations — writes the chosen
    // conversation_key into the node config, which changes the conversation_id
    // useAgentChat is subscribed to.
    const setConversationKey = useCallback(
        (key: string) => {
            if (isReadOnly) return;
            onConfigChange({ ...config, conversation_key: key });
        },
        [config, isReadOnly, onConfigChange]
    );

    const conversationsState = useAgentChatConversations(
        workflowId,
        id,
        activeKey,
        setConversationKey
    );
    // Memoize so submit's identity doesn't churn on every list refresh — the
    // raw conversations array gets a new reference on every poll/refetch even
    // when its contents are unchanged.
    const activeConv = useMemo(
        () =>
            conversationsState.conversations.find(
                (c) => c.conversation_key === activeKey
            ),
        [conversationsState.conversations, activeKey]
    );

    const handleSwitchToConversation = useCallback(
        (conv: AgentConversationSummary) => {
            if (isReadOnly) return;
            const currentModelValue =
                (config.model as string) || DEFAULT_AGENT_MODEL;
            if (harnessOf(conv.agent_model) === harnessOf(currentModelValue)) {
                setConversationKey(conv.conversation_key);
                return;
            }
            const targetModel = resolveRunModel(conv.agent_model);
            if (!targetModel) {
                // legacy/cli — can't recover the original CLI. Load the thread; the
                // amber cross-harness tag warns the user about event-shape mixing.
                setConversationKey(conv.conversation_key);
                return;
            }
            onConfigChange({
                ...config,
                conversation_key: conv.conversation_key,
                model: targetModel,
            });
        },
        [config, isReadOnly, onConfigChange, setConversationKey]
    );

    // Generic config writer used by the sidebar fields (system prompt, temperature, …).
    const patchConfig = useCallback(
        (patch: Record<string, unknown>) => {
            if (isReadOnly) return;
            onConfigChange({ ...config, ...patch });
        },
        [config, isReadOnly, onConfigChange]
    );

    const [credentialError, setCredentialError] = useState<string | null>(null);
    // Clear the pre-flight error the moment the user fixes credentials or
    // switches to a different model — they shouldn't have to send-and-fail again.
    useEffect(() => {
        setCredentialError(null);
    }, [credentialIds, selectedModel]);

    // Drives the error banner's shortcut buttons: a signal that pops the header
    // model picker, and a flag that opens the Add-credential popup.
    const [modelPickerSignal, setModelPickerSignal] = useState(0);
    const [credDialogOpen, setCredDialogOpen] = useState(false);
    const [shareOpen, setShareOpen] = useState(false);
    // Test mode replaces the chat surface in place — a mode to leave, not a
    // page to navigate to. Session-store state, not useState: switching
    // workspace tabs unmounts this block, and test mode must survive it.
    const [testMode, setTestMode] = useValtioState<boolean>(
        'agentChatBlock',
        `test-mode-${id}`,
        false
    );
    // The Setup tab's "Open Test Run" hand-off: sticky state, not a window
    // event, so it survives this block mounting after the flag was set.
    const [pendingTest, setPendingTest] = useValtioState<boolean>(
        'agentChatBlock',
        `open-test-${workflowId ?? 'unknown'}`,
        false
    );
    useEffect(() => {
        if (pendingTest && workflowId) {
            setPendingTest(false);
            setTestMode(true);
        }
    }, [pendingTest, workflowId, setPendingTest, setTestMode]);

    // Canonical provider resolution — matches AgentCredentialsForm.useMemo's
    // `getModelById(effective)?.provider ?? inferProviderFromPrefix(effective)`
    // chain. This is what the credentials form uses to compute the credential
    // type, so the validator and the auto-cleanup MUST use the same path or
    // they'll disagree on what `agent_*` key the user is supposed to have.
    // String-matching helpers like NodeCredentials' getProviderFromModelId fall
    // back to "model includes 'claude' → anthropic" which is wrong for CLI
    // harnesses (claude-code's canonical provider is 'claude_code', not
    // 'anthropic').
    const { getModelById } = useModels();
    const effectiveProvider = useMemo(() => {
        const effective = getAgentEffectiveModel(
            selectedModel,
            config as Record<string, unknown>
        );
        return (
            getModelById(effective)?.provider ??
            inferProviderFromPrefix(effective) ??
            null
        );
    }, [selectedModel, config, getModelById]);

    // Auto-clean stale `agent_<provider>` credential links when the model
    // changes provider. The user-reported failure mode: link a claude-code
    // credential, switch the model to an OpenRouter one, the backend still
    // gets the claude-code token and forwards it to OpenRouter → 401. The
    // AgentCredentialsForm already enforces "one credential at a time, must
    // match the current model" when you interact with it; this effect extends
    // that invariant to model swaps that happen outside the form (e.g. via
    // the header model picker). After cleanup the user is in the "no credential
    // linked" state — for usage-based providers (openrouter/openai/anthropic/
    // gemini) the run still works via NoClick's billing; otherwise the
    // Credentials panel surfaces an "add credential" prompt.
    //
    // "Valid for this provider" is getAgentCredentialIdForProvider — the SAME
    // resolver the form/validator use — NOT a naive `agent_<provider>` match. The
    // naive match deleted valid OAuth-alias credentials (e.g. agent_claude_code_oauth
    // for claude_code) on every mount, so navigating to the Interface tab reset the
    // agent's credential to none.
    const cleanedProviderRef = useRef<string | null>(null);
    useEffect(() => {
        if (isReadOnly || !onCredentialIdsChange) return;
        if (!effectiveProvider) {
            cleanedProviderRef.current = null;
            return;
        }
        if (cleanedProviderRef.current === effectiveProvider) return;
        cleanedProviderRef.current = effectiveProvider;
        const linked = credentialIds || {};
        const staleKeys = staleCredentialKeysForProvider(
            linked,
            effectiveProvider as ModelProvider
        );
        if (staleKeys.length === 0) return;
        const next: Record<string, string> = { ...linked };
        for (const k of staleKeys) delete next[k];
        onCredentialIdsChange(next);
    }, [effectiveProvider, credentialIds, isReadOnly, onCredentialIdsChange]);

    const { createNew } = conversationsState;

    // A conversation is bound to the model it started with — each harness keeps
    // independent conversation state, and a different provider means a different
    // credential and route. So a picker that has
    // moved on means the NEXT SEND starts a fresh conversation under it, with
    // the previous thread carried over as context (see submitText).
    //
    // Decided here, ACTED ON at send. This used to be two mechanisms on
    // different triggers — an effect that minted the instant the harness
    // changed, and a later provider check — and both emptied the transcript
    // before the user had sent anything. Whichever fired first decided the
    // outcome, and a message dispatched near that moment landed in the thread
    // being left. As one step inside submitText there is no interleaving to
    // get wrong, and nothing changes until the user actually sends.
    // What this thread is actually running. The conversations list is the
    // nominal source, but it is only refetched when the History popover opens,
    // so a thread minted in this session is missing from it — and an unknown
    // model silently read as "same as picked", which is how one conversation
    // took consecutive turns through different harnesses.
    const conversationModel =
        resolveRunModel(activeConv?.agent_model) ??
        getAgentChatSession(conversationId).lastSentModel ??
        selectedModel;

    const willMintNewConversation = useMemo(
        () =>
            !isReadOnly &&
            conversationNeedsFreshThread({
                sendModel: conversationModel,
                selectedModel,
                config: config as Record<string, unknown>,
                resolveProvider: (m) =>
                    getModelById(m)?.provider ??
                    inferProviderFromPrefix(m) ??
                    null,
            }),
        [isReadOnly, conversationModel, selectedModel, config, getModelById]
    );

    /** The model this send will actually run under — the single answer both the
     *  credential pre-flight and the dispatch use, so they cannot disagree
     *  about what is about to happen.
     *
     *  Always the pick. A send that mints runs it by definition, and a send
     *  that continues can only differ from the thread within the same harness
     *  and provider (anything else mints) — same credential, same route, and
     *  LLM-path history is model-agnostic, so Sonnet→Opus mid-thread is safe.
     *  Honouring the thread's own model here instead silently discarded such
     *  picks AND snapped the picker back: the send-time config patch wrote the
     *  thread's model over the pick the user had just persisted. */
    const effectiveSendModel = selectedModel;

    // CLI-harness sub-model (codex_model / claude_code_model / …). Hoisted so
    // the JSX render doesn't IIFE-recompute it every cycle.
    const subModelField = useMemo(
        () => getCliSubModelField(selectedModel),
        [selectedModel]
    );
    // Fall back to the wrapper's schema default so legacy nodes (created before
    // seeding, sub-model never persisted) show the model that will actually run
    // instead of "Select…". Undefined for codex/claude-code (out of scope).
    const subModelValue = subModelField
        ? (((config[subModelField.configKey] as string | undefined)?.trim() ||
              WRAPPER_SUBMODEL_DEFAULT_BY_MODEL[selectedModel]) ??
          '')
        : '';
    const handleSubModelSelect = useCallback(
        (value: string) => {
            if (!subModelField) return;
            patchConfig({ [subModelField.configKey]: value });
        },
        [subModelField, patchConfig]
    );

    // Pre-flight credential verdict for the CURRENT send target — the exact
    // check submit() enforces, memoized so the UI can warn BEFORE a send is
    // attempted. Without the standing warning, a missing credential read as a
    // broken send button: the pre-flight returned before addUserMessage, the
    // chat stayed empty, and the empty state rendered INSTEAD of the transcript
    // that owns the error banner — zero feedback.
    //
    // The conversation owns its harness — agent_model is locked when the
    // conversation is first persisted, and that's what the run must
    // honor, not the picker (which can drift mid-render or via races).
    // Wrapper harnesses (openclaw/opencode/hermes) carry the real provider on
    // their sub-model field (openclaw_model → openrouter/…), not the harness id.
    // Resolve the effective model first — same path as the effectiveProvider memo
    // — so the validator demands the SAME agent_<provider> credential the backend
    // loads. Using the bare harness id asked for a nonexistent `agent_openclaw`
    // credential and blocked every send for a correctly-linked openrouter cred.
    const sendCredentialError = useMemo(
        () =>
            validateAgentSendCredentials({
                // The model that will actually run — the same value submitText
                // dispatches. Validating the conversation's model while the
                // send switches to the picked one is what produced "the linked
                // credential is for opencode, but this model routes through
                // openrouter" on a correctly-configured agent.
                sendModel: effectiveSendModel,
                config: config as Record<string, unknown>,
                credentialIds,
                resolveProvider: (m) =>
                    getModelById(m)?.provider ??
                    inferProviderFromPrefix(m) ??
                    null,
            }),
        [effectiveSendModel, config, credentialIds, getModelById]
    );

    // Attachment tray (images/files) — uploaded to R2 as they're added, so a
    // send only has to reference the ready set.
    const {
        attachments,
        addFiles,
        removeAttachment,
        clearAttachments,
        uploading: attachmentsUploading,
        readyAttachments,
    } = useChatAttachments(workflowId, id);

    const submitText = useCallback(
        (raw: string) => {
            if (isReadOnly) {
                onInteraction?.();
                return;
            }
            const text = raw.trim();
            const hasAttachments = readyAttachments.length > 0;
            if (
                (!text && !hasAttachments) ||
                attachmentsUploading ||
                isStreaming ||
                submittingRef.current
            )
                return;
            if (sendCredentialError) {
                setCredentialError(sendCredentialError);
                return;
            }
            setCredentialError(null);
            // Claim the guard synchronously (released next tick, by when isStreaming has
            // flushed and takes over) so a same-tick second click can't dispatch a 2nd run.
            submittingRef.current = true;
            setTimeout(() => {
                submittingRef.current = false;
            }, 0);

            // Everything the switch involves happens HERE, in order, before
            // anything is dispatched: read the thread, mint the key, send into
            // it. The key is handed to the sender rather than read back off the
            // node config, which createNew() writes asynchronously.
            const carried = willMintNewConversation
                ? buildCarryOverContext(messages)
                : '';
            const conversationKey = willMintNewConversation
                ? createNew()
                : undefined;
            const targetConversationId = conversationKey
                ? deriveAgentChatConversationId(workflowId, id, conversationKey)
                : conversationId;
            // Remember what this thread runs, against the conversation the turn
            // is actually going into. The list will not tell us until the
            // History popover is opened, and the next send has to know.
            const target = getAgentChatSession(targetConversationId);
            target.lastSentModel = effectiveSendModel;

            // Echo content for the user bubble: attached images render as
            // thumbnails, other files as chips — same shapes the persisted
            // transcript restores, so the reconciler's replacement matches.
            const echoContent = readyAttachments
                .filter(isImageAttachment)
                .map((a) => ({
                    type: 'image_url' as const,
                    image_url: { url: a.url },
                }));
            const echoFiles = readyAttachments
                .filter((a) => !isImageAttachment(a))
                .map((a) => ({
                    name: a.name,
                    url: a.url,
                    mimeType: a.mimeType,
                }));

            // The user always wants to follow their own send, even if they'd scrolled up.
            pinScroll();
            // Echo the user message locally — the backend doesn't replay
            // chat:message for the sender, so without this the bubble doesn't
            // appear until the agent's first response chunk arrives.
            if (conversationKey) {
                // Minting: addUserMessage would write to the conversation being
                // LEFT, because createNew() propagates its key through the node
                // config and conversationId has not caught up yet. The echo has
                // to be placed on the thread the turn is going into, along with
                // the turns it carried — otherwise the user watches a blank
                // transcript with a step timeline and no sign of their own
                // message until the reply lands.
                //
                // The same content arrives persisted a moment later (the block
                // rides the message and is split back out); the reconciler
                // REPLACES the transcript with that, so this seed is a stand-in,
                // not a second copy.
                target.messages = [
                    ...splitCarryOverContext(carried).carried.map((turn) => ({
                        isUser: turn.isUser,
                        text: turn.text,
                        isComplete: true,
                        carriedOver: true,
                    })),
                    {
                        isUser: true,
                        text,
                        isComplete: true,
                        content: echoContent.length ? echoContent : undefined,
                        attachments: echoFiles.length ? echoFiles : undefined,
                    },
                ];
                target.isStreaming = true;
            } else {
                addUserMessage(
                    text,
                    echoContent.length ? echoContent : undefined,
                    echoFiles.length ? echoFiles : undefined
                );
            }
            // The model reads the carried thread; the bubble above shows only
            // what the user typed. The transcript puts those turns back as real
            // messages once the send is persisted (splitCarryOverContext).
            onAgentChatSend?.(
                id,
                withCarriedContext(text, carried),
                effectiveSendModel,
                conversationKey,
                readyAttachments.length ? readyAttachments : undefined
            );
            setDraft('');
            clearAttachments();
            requestAnimationFrame(() => textareaRef.current?.focus());
        },
        [
            id,
            isReadOnly,
            isStreaming,
            onAgentChatSend,
            onInteraction,
            addUserMessage,
            sendCredentialError,
            pinScroll,
            willMintNewConversation,
            effectiveSendModel,
            messages,
            createNew,
            conversationId,
            workflowId,
            readyAttachments,
            attachmentsUploading,
            clearAttachments,
        ]
    );

    // Takes no argument on purpose: the composer wires this straight to onClick,
    // so a positional parameter would be handed a MouseEvent.
    const submit = useCallback(() => submitText(draft), [submitText, draft]);

    // An opening message handed over by the Run popup. Drained here rather than
    // sent there so the user's bubble is echoed and the streaming state is live —
    // a raw workflow:execute produces neither, which read as the message
    // vanishing.
    //
    // A blocker LEAVES IT QUEUED rather than consuming it: submitText refuses
    // silently, and the queue is consumed before it does, so anything taken
    // while blocked is simply gone. Staying queued means this re-runs when the
    // blocker lifts and sends it then, which is what the user asked for when
    // they typed it. Nothing here has to know about a pending model switch —
    // submitText mints and sends in one step.
    useEffect(() => {
        if (
            isReadOnly ||
            isStreaming ||
            sendCredentialError ||
            attachmentsUploading
        )
            return;
        const queued = takeQueuedAgentChatSend(workflowId, id);
        if (queued) submitText(queued);
    }, [
        workflowId,
        id,
        isReadOnly,
        isStreaming,
        sendCredentialError,
        attachmentsUploading,
        submitText,
    ]);

    const agentLabel = (config.label as string) || 'Agent';
    const systemPrompt = (config.system_prompt as string) ?? '';
    const temperature =
        typeof config.temperature === 'number' ? config.temperature : 0.7;

    // Sidebar width persisted across mounts. Drag handle on the left edge
    // updates this via mousemove; min/max keep it sane.
    const [sidebarWidth, setSidebarWidth] = useCachedValtioState<number>(
        'agent-chat',
        'sidebarWidth',
        320,
        true // skipRedisSync — purely local UI preference
    );
    const [sidebarCollapsed, setSidebarCollapsed] =
        useCachedValtioState<boolean>(
            'agent-chat',
            'sidebarCollapsed',
            false,
            true
        );

    // The settings panel is a flex sibling on wide layouts but a slide-in
    // overlay drawer when the chat region is too narrow to hold both side by
    // side. The decision is driven by the region's OWN width (ResizeObserver
    // below), not the viewport — so it also engages when the AI builder drawer
    // or a split view steals horizontal space, which a viewport media query
    // can't see. Its own session-local open state keeps the chat full-width on
    // load and stops the persisted desktop `sidebarCollapsed` preference from
    // forcing the drawer open when narrow.
    const containerRef = useRef<HTMLDivElement>(null);
    const [regionWidth, setRegionWidth] = useState(0);
    useEffect(() => {
        const el = containerRef.current;
        if (!el) return;
        setRegionWidth(el.getBoundingClientRect().width);
        const ro = new ResizeObserver((entries) => {
            for (const e of entries) setRegionWidth(e.contentRect.width);
        });
        ro.observe(el);
        return () => ro.disconnect();
    }, []);
    // Below this the panel would squash the chat past usability (chat ~420px +
    // panel ~240px + resize handle); overlay it instead.
    const isNarrow = regionWidth > 0 && regionWidth < 700;
    const [mobileSettingsOpen, setMobileSettingsOpen] = useState(false);
    const settingsOpen = isNarrow ? mobileSettingsOpen : !sidebarCollapsed;
    const openSettings = useCallback(() => {
        if (isNarrow) setMobileSettingsOpen(true);
        else setSidebarCollapsed(false);
    }, [isNarrow, setSidebarCollapsed]);
    const closeSettings = useCallback(() => {
        if (isNarrow) setMobileSettingsOpen(false);
        else setSidebarCollapsed(true);
    }, [isNarrow, setSidebarCollapsed]);

    const draggingRef = useRef(false);

    // Error-banner shortcuts. "Add credential" opens a centered popup with the
    // provider's credential form; "Change model" pops the header picker so the
    // user can switch to a model that doesn't need this credential.
    const handleFixModel = useCallback(() => {
        setModelPickerSignal((s) => s + 1);
    }, []);
    const handleFixCredential = useCallback(() => {
        setCredDialogOpen(true);
    }, []);

    // The rehearsal renders provider icons; inside the workspace they come from
    // the client node registry (the same Icon components the canvas draws),
    // not the server catalog the design route serializes. Keyed by the
    // BACKEND'S tool-name prefix (_provider_slug: type minus "automation-",
    // hyphens → underscores) so any wired provider's tool rows find their
    // logo — a fixed four-key map left everything else on the generic plug.
    const rehearsalIcons = useRehearsalIcons();
    // Trigger/tool nodes wired to this agent whose credentials are missing —
    // the workflow-level half of readiness (the agent's own model credential
    // has its own pill above the composer).
    const wiringUnmet = useWorkflowReadiness(
        !isReadOnly ? (workflowId ?? null) : null,
        id
    );

    // Test sits to Share's left: rehearse the agent against a staged trigger —
    // real agent, fabricated world — before pointing it at anything live. The
    // flask is the rehearsal's mark everywhere it appears.
    const testButton =
        !isReadOnly && workflowId ? (
            <button
                type="button"
                onClick={() => setTestMode(true)}
                aria-label="Test agent"
                title="Test the agent against a staged trigger"
                data-testid="agent-chat-test-button"
                className="shrink-0 flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border border-border/60 hover:border-border hover:bg-foreground/[0.04] transition-colors text-muted-foreground hover:text-foreground"
            >
                <FlaskConical className="w-3.5 h-3.5" />
                <span className="text-sm hidden @xl:inline">Test</span>
            </button>
        ) : null;

    // Share lives in the chat header's right cluster — outside the settings
    // panel, so the entry point stays visible whether the panel is open or
    // collapsed. Styled to match the History pill in the left cluster.
    const shareButton =
        !isReadOnly && workflowId ? (
            <button
                type="button"
                onClick={() => setShareOpen(true)}
                aria-label="Share agent"
                title="Share agent"
                data-testid="agent-chat-share-button"
                className="shrink-0 flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border border-border/60 hover:border-border hover:bg-foreground/[0.04] transition-colors text-muted-foreground hover:text-foreground"
            >
                <Share className="w-3.5 h-3.5" />
                <span className="text-sm hidden @xl:inline">Share</span>
            </button>
        ) : null;

    const startResize = useCallback(
        (e: React.MouseEvent) => {
            e.preventDefault();
            draggingRef.current = true;
            const startX = e.clientX;
            const startWidth = sidebarWidth;
            const onMove = (ev: MouseEvent) => {
                if (!draggingRef.current) return;
                // Dragging left widens the sidebar (we're on its left edge).
                const next = Math.min(
                    SIDEBAR_MAX,
                    Math.max(SIDEBAR_MIN, startWidth - (ev.clientX - startX))
                );
                setSidebarWidth(next);
            };
            const onUp = () => {
                draggingRef.current = false;
                document.removeEventListener('mousemove', onMove);
                document.removeEventListener('mouseup', onUp);
                document.body.style.cursor = '';
                document.body.style.userSelect = '';
            };
            document.addEventListener('mousemove', onMove);
            document.addEventListener('mouseup', onUp);
            document.body.style.cursor = 'col-resize';
            document.body.style.userSelect = 'none';
        },
        [sidebarWidth, setSidebarWidth]
    );

    if (testMode) {
        return (
            <div ref={containerRef} className="w-full h-full overflow-y-auto bg-background">
                <RehearsalScreen
                    icons={rehearsalIcons}
                    live={workflowId ? { workflowId } : undefined}
                    onClose={() => setTestMode(false)}
                    className="px-4 sm:px-6 py-6"
                />
            </div>
        );
    }

    return (
        <div ref={containerRef} className="w-full h-full flex bg-background relative">
            {/* Left column: chat surface. Stretches edge-to-edge of the sidebar. */}
            <div className="flex-1 min-w-0 flex flex-col">
                {/* Header — no horizontal divider; the model picker is the anchor,
            history sits to its right; Share (always) and the settings-open
            pill (when collapsed) live on the far right. */}
                <div className="@container px-3 sm:px-6 py-4 shrink-0 flex items-center justify-between gap-3">
                    <div className="flex items-center gap-1 min-w-0">
                        <AgentModelPicker
                            selectedModelId={selectedModel}
                            onSelect={handleModelSelect}
                            openSignal={modelPickerSignal}
                        />
                        <AgentChatHistory
                            conversations={conversationsState.conversations}
                            activeKey={activeKey}
                            currentModel={selectedModel}
                            isLoading={conversationsState.isLoading}
                            onSwitchTo={handleSwitchToConversation}
                            onDelete={conversationsState.deleteOne}
                            onCreateNew={() => conversationsState.createNew()}
                            onRefresh={() => {
                                void conversationsState.refresh();
                            }}
                            isReadOnly={!!isReadOnly}
                        />
                        <WorkspaceFilesMenu
                            state={workspaceFiles}
                            onRefresh={() => {
                                void refreshWorkspaceFiles();
                            }}
                            onPreview={setWorkspacePreview}
                        />
                    </div>
                    <div className="flex items-center gap-1.5 shrink-0">
                        {testButton}
                        {shareButton}
                        {!settingsOpen ? (
                            <button
                                type="button"
                                onClick={openSettings}
                                aria-label="Show settings"
                                title="Show settings"
                                className="shrink-0 flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border border-border/60 hover:border-border hover:bg-foreground/[0.04] transition-colors text-muted-foreground hover:text-foreground"
                            >
                                <PanelRightOpen className="w-3.5 h-3.5" />
                                <span className="text-sm hidden @xl:inline">Settings</span>
                            </button>
                        ) : null}
                    </div>
                </div>

                {/* Transcript — constrained to a centered reading column (same
            max-w-3xl as the public share page) so long answers wrap at a
            readable measure instead of spanning the whole panel. */}
                <div
                    ref={scrollRef}
                    onScroll={onTranscriptScroll}
                    // Which thread this block is showing, and how many turns it
                    // has. Both are derived from state a test cannot reach, and
                    // a mismatch between them and the session store is exactly
                    // how a minted conversation renders as empty.
                    data-agent-conversation={conversationId}
                    data-agent-message-count={messages.length}
                    className="flex-1 min-h-0 overflow-y-auto scrollbar-subtle"
                >
                    <div
                        className={cn(
                            'mx-auto w-full max-w-3xl px-3 sm:px-6 py-6',
                            messages.length === 0 &&
                                !(isStreaming || remoteBusy) &&
                                !credentialError &&
                                !errorReason &&
                                'flex h-full items-center justify-center'
                        )}
                    >
                        {/* An error to show yields to the transcript — its trailing banner
                (+ Add credential / Change model actions) is the feedback for a
                failed send pre-flight, and the empty state has no banner slot. */}
                        {messages.length === 0 &&
                        !(isStreaming || remoteBusy) &&
                        !credentialError &&
                        !errorReason ? (
                            <div
                                data-testid="agent-chat-empty"
                                className="flex flex-col items-center gap-4 pb-16 text-center"
                            >
                                {/* Mini preview of the agent node: the REAL canvas tile —
                    identical container classes, normal-size logo, caption, and
                    handle dots from AIAgentNode — rendered at the node's true
                    200×140 and CSS-scaled down. Scaling the real thing keeps
                    proportions/colors faithful by construction (a hand-sized
                    replica drifted). */}
                                <div className="relative h-[84px] w-[120px]">
                                    <div className="absolute left-0 top-0 h-[140px] w-[200px] origin-top-left scale-[0.6]">
                                        <div className="relative h-full w-full">
                                            <div className="flex h-full w-full flex-col items-center justify-center overflow-hidden rounded-2xl border border-border bg-card p-4 shadow-lg dark:border-zinc-700/40 dark:bg-[radial-gradient(circle_at_30%_30%,rgba(63,63,70,0.4),rgba(9,9,11,0.95))]">
                                                <div className="flex flex-col items-center gap-2">
                                                    <AgentModelIcon
                                                        model={selectedModel}
                                                        variant="normal"
                                                    />
                                                    <div className="text-xs font-medium text-muted-foreground">
                                                        Agent Model
                                                    </div>
                                                </div>
                                            </div>
                                            <span className="absolute -left-2 top-1/2 h-4 w-4 -translate-y-1/2 rounded-full border-2 border-zinc-400 bg-zinc-300 opacity-70 dark:border-zinc-500 dark:bg-zinc-400" />
                                            <span className="absolute -right-2 top-1/2 h-4 w-4 -translate-y-1/2 rounded-full border-2 border-zinc-400 bg-zinc-300 opacity-70 dark:border-zinc-500 dark:bg-zinc-400" />
                                            <span className="absolute -bottom-2 left-1/2 h-4 w-4 -translate-x-1/2 rounded-full border-2 border-zinc-400 bg-zinc-300 opacity-70 dark:border-zinc-500 dark:bg-zinc-400" />
                                        </div>
                                    </div>
                                </div>
                                <div>
                                    {/* Fixed title — interpolating the label doubled up with the
                      default ("Chat with Agent Chat"). */}
                                    <p className="text-sm font-medium text-foreground/90">
                                        Chat with Agent Node
                                    </p>
                                    <p className="mt-1 max-w-sm text-xs text-muted-foreground/70">
                                        You&rsquo;re chatting with this agent
                                        node from your workflow. Replies and
                                        tool calls stream here.
                                    </p>
                                </div>
                            </div>
                        ) : (
                            <AgentChatTranscript
                                messages={messages}
                                onOpenWorkspaceFile={openWorkspaceFile}
                                onBuilderDecision={handleBuilderDecision}
                                // remoteBusy keeps the working indicator lit for turns this tab
                                // didn't start (isStreaming is send-local); presence itself does
                                // not control whether this tab can submit.
                                isStreaming={isStreaming || remoteBusy}
                                errorReason={credentialError ?? errorReason}
                                // Fix actions are the CREDENTIAL error's recovery path — showing
                                // "Add credential" under an unrelated failure (a Redis timeout,
                                // a provider 500) points the user at the wrong fix. That covers
                                // BACKEND-classified credential failures too (revoked key: the
                                // pre-flight checks linkage, not validity): provider_errors'
                                // rewrites all name the credential, so a text probe is the
                                // available signal until the classifier ships a structured flag.
                                errorActions={
                                    (credentialError ||
                                        (errorReason &&
                                            /credential/i.test(errorReason))) &&
                                    !isReadOnly ? (
                                        <div className="flex flex-wrap items-center gap-2 mt-2">
                                            {/* Add credential leads — it's the most common fix — and
                      gets a key icon + emphasis so the eye lands on it. */}
                                            {onCredentialIdsChange ? (
                                                <button
                                                    type="button"
                                                    onClick={
                                                        handleFixCredential
                                                    }
                                                    data-testid="agent-chat-error-add-credential"
                                                    className="inline-flex items-center gap-1.5 text-xs font-medium text-foreground bg-foreground/[0.12] hover:bg-foreground/[0.18] border border-foreground/20 rounded-md px-2.5 py-1 transition-colors"
                                                >
                                                    <KeyRound className="w-3.5 h-3.5" />
                                                    Add credential
                                                </button>
                                            ) : null}
                                            <button
                                                type="button"
                                                onClick={handleFixModel}
                                                data-testid="agent-chat-error-change-model"
                                                className="text-xs font-medium text-foreground bg-foreground/[0.06] hover:bg-foreground/[0.12] border border-border dark:border-zinc-700 rounded-md px-2.5 py-1 transition-colors"
                                            >
                                                Change model
                                            </button>
                                        </div>
                                    ) : null
                                }
                            />
                        )}
                    </div>
                </div>

                {/* Standing credential warning — visible BEFORE any send is attempted,
            so a missing credential never reads as a broken send button. The
            whole pill takes the action its own text names: normally that is
            Add credential, but a chat pinned to another model cannot be fixed
            that way, so there it starts a fresh conversation instead. It
            disappears the moment the cause is gone (sendCredentialError
            recomputes). Deliberately does NOT disable the composer: a send
            attempt additionally raises the red banner with the fix actions. */}
                {/* One warning stack: the agent-credential pill and the
                    unconnected-wiring card share the readiness vocabulary
                    (same amber recipe, same radius) and a single rhythm —
                    two banners in two styles read as two systems. */}
                {!isReadOnly && (sendCredentialError || wiringUnmet.length > 0) && (
                    <div className="shrink-0 px-6 pb-2">
                        <div className="mx-auto w-full max-w-3xl space-y-2">
                            {sendCredentialError ? (
                                <button
                                    type="button"
                                    onClick={handleFixCredential}
                                    data-testid="agent-chat-credential-hint"
                                    className="flex w-full items-center gap-2.5 rounded-xl border border-amber-400/25 bg-amber-400/[0.04] px-4 py-3 text-left text-[12.5px] transition-colors hover:bg-amber-400/[0.08]"
                                >
                                    <KeyRound className="h-4 w-4 shrink-0 text-amber-400" />
                                    <span className="min-w-0 flex-1 text-amber-800 dark:text-amber-100/95">
                                        {sendCredentialError}
                                    </span>
                                    <span className="shrink-0 font-medium text-amber-700 underline underline-offset-2 dark:text-amber-300">
                                        Add credential
                                    </span>
                                </button>
                            ) : null}
                            {wiringUnmet.length > 0 && (
                                <ReadinessCard
                                    unmet={wiringUnmet}
                                    // A banner above the composer can never afford
                                    // the full per-service stack — always one card.
                                    compact
                                    onConnect={(item) =>
                                        document.dispatchEvent(
                                            new CustomEvent('noclick:open-setup-step', {
                                                detail: {
                                                    workflowId,
                                                    stepKey: `${item.nodeId}:credentials`,
                                                },
                                            })
                                        )
                                    }
                                />
                            )}
                        </div>
                    </div>
                )}

                {/* Chatbox — the composer centers itself on the same max-w-3xl column. */}
                <AgentChatComposer
                    value={draft}
                    onChange={setDraft}
                    onSubmit={submit}
                    placeholder={`Message ${agentLabel}`}
                    inputDisabled={isReadOnly}
                    sendDisabled={
                        (!draft.trim() && readyAttachments.length === 0) ||
                        attachmentsUploading ||
                        isStreaming ||
                        isReadOnly
                    }
                    textareaRef={textareaRef}
                    attachments={attachments}
                    onAddFiles={isReadOnly ? undefined : addFiles}
                    onRemoveAttachment={removeAttachment}
                />
            </div>

            {/* Right column: agent settings. Desktop = resizable flex sibling;
                mobile = slide-in overlay drawer (backdrop closes it) so the chat
                stays full-width instead of being squashed to a sliver. */}
            {!settingsOpen ? null : (
                <aside
                    className={cn(
                        'border-l border-border/60 dark:border-zinc-800/60 flex flex-col',
                        isNarrow
                            ? 'absolute inset-0 z-50 w-full shadow-2xl bg-background dark:bg-zinc-950'
                            : 'shrink-0 relative bg-foreground/[0.03] dark:bg-zinc-950/30'
                    )}
                    style={isNarrow ? undefined : { width: sidebarWidth }}
                >
                    {/* Drag handle pinned to the left edge (wide layout only). */}
                    {!isNarrow ? (
                        <div
                            onMouseDown={startResize}
                            className="absolute left-0 top-0 bottom-0 -translate-x-1/2 w-2 cursor-col-resize z-10 group"
                            aria-label="Resize settings sidebar"
                        >
                            <div className="absolute inset-y-0 left-1/2 w-px bg-transparent group-hover:bg-accent dark:group-hover:bg-zinc-700 transition-colors" />
                        </div>
                    ) : null}

                    <div className="px-5 py-4 border-b border-border/60 dark:border-zinc-800/60 shrink-0 flex items-start justify-between gap-3">
                        <div>
                            <h3 className="text-sm font-semibold text-foreground tracking-tight">
                                Settings
                            </h3>
                            <p className="text-[11px] text-muted-foreground dark:text-zinc-500 mt-0.5">
                                Changes save to the agent node.
                            </p>
                        </div>
                        <button
                            type="button"
                            onClick={closeSettings}
                            aria-label="Collapse settings"
                            title="Collapse settings"
                            className="shrink-0 text-muted-foreground hover:text-foreground bg-foreground/[0.04] hover:bg-foreground/[0.08] border border-border hover:border-border dark:hover:border-zinc-700 rounded-lg p-1.5 transition-colors"
                        >
                            <PanelRightClose className="w-4 h-4" />
                        </button>
                    </div>

                    <div className="flex-1 min-h-0 overflow-y-auto scrollbar-subtle px-5 py-5 space-y-6">
                        {/* Sub-model picker for CLI harnesses (codex, claude-code, opencode,
              openclaw, hermes). Each harness wraps an underlying model
              the user can pick. For regular LLMs this renders nothing — the
              header model picker is the only model selector. */}
                        {subModelField ? (
                            <section data-testid="agent-chat-sub-model-section">
                                <label className="block text-[11px] uppercase tracking-wider text-muted-foreground dark:text-zinc-500 mb-2">
                                    {subModelField.label}
                                </label>
                                <AgentSubModelPicker
                                    fieldName={subModelField.fieldName}
                                    selectedModelId={subModelValue}
                                    onSelect={handleSubModelSelect}
                                    disabled={isReadOnly}
                                />
                                <p className="text-[10px] text-muted-foreground/70 dark:text-zinc-600 mt-1.5">
                                    Underlying model {selectedModel} will run.
                                </p>
                            </section>
                        ) : null}

                        {/* Credentials — adapts to the selected model's provider. */}
                        {onCredentialIdsChange ? (
                            <section data-testid="agent-chat-credentials-section">
                                <label className="block text-[11px] uppercase tracking-wider text-muted-foreground dark:text-zinc-500 mb-2">
                                    Credentials
                                </label>
                                <AgentCredentialsForm
                                    nodeData={config as Record<string, unknown>}
                                    credentialIds={credentialIds ?? {}}
                                    onCredentialIdsChange={
                                        onCredentialIdsChange
                                    }
                                />
                            </section>
                        ) : null}

                        {/* Triggers + Tools — the agent's canvas wiring, editable from the
              chat so interface users never need the canvas: triggers fire the
              agent with their event as its message; tools are integrations
              the agent may act on (allowlisted actions). */}
                        {agentWiring && (
                            <AgentWiringSections
                                wiring={agentWiring}
                                isReadOnly={isReadOnly}
                                onAdd={onAgentWiringAdd}
                                onRemove={onAgentWiringRemove}
                                onWiredNodeConfigPatch={onWiredNodeConfigPatch}
                                onWiredNodeCredentialsChange={
                                    onWiredNodeCredentialsChange
                                }
                                getWiredNodeData={getWiredNodeData}
                                workflowId={workflowId}
                            />
                        )}

                        {/* Capabilities — the agent's powerful platform tools, each an
              explicit opt-in/out (config flags the backend gates injection
              on): workflow self-editing via the AI builder, and emailing the
              owner when they're away. */}
                        <section data-testid="agent-chat-capabilities-section">
                            <label className="block text-[11px] uppercase tracking-wider text-muted-foreground dark:text-zinc-500 mb-2">
                                Capabilities
                            </label>
                            <div className="rounded-lg border border-border bg-card dark:bg-transparent divide-y divide-border/60 dark:divide-zinc-800/60">
                                <div className="flex items-start justify-between gap-3 px-3 py-2.5">
                                    <div className="min-w-0">
                                        <div className="text-xs font-medium text-foreground">
                                            Workflow edits
                                        </div>
                                        <p className="text-[10px] text-muted-foreground/70 dark:text-zinc-600 mt-0.5 leading-relaxed">
                                            Agent can propose changes to this
                                            workflow via the AI builder (asks
                                            your approval here; runs headlessly
                                            on triggers).
                                        </p>
                                    </div>
                                    <Switch
                                        checked={
                                            (config.enable_prompt_builder as
                                                | string
                                                | undefined) !== 'false'
                                        }
                                        onCheckedChange={(v) =>
                                            patchConfig({
                                                enable_prompt_builder: v
                                                    ? 'true'
                                                    : 'false',
                                            })
                                        }
                                        disabled={isReadOnly}
                                        data-testid="agent-chat-toggle-workflow-edits"
                                        aria-label="Allow workflow edits"
                                    />
                                </div>
                                <div className="flex items-start justify-between gap-3 px-3 py-2.5">
                                    <div className="min-w-0">
                                        <div className="text-xs font-medium text-foreground">
                                            Email updates
                                        </div>
                                        <p className="text-[10px] text-muted-foreground/70 dark:text-zinc-600 mt-0.5 leading-relaxed">
                                            When you're away, the agent can
                                            email you questions, links, and
                                            failure reports — reply to the email
                                            to answer it.
                                        </p>
                                    </div>
                                    <Switch
                                        checked={
                                            (config.enable_email_updates as
                                                | string
                                                | undefined) !== 'false'
                                        }
                                        onCheckedChange={(v) =>
                                            patchConfig({
                                                enable_email_updates: v
                                                    ? 'true'
                                                    : 'false',
                                            })
                                        }
                                        disabled={isReadOnly}
                                        data-testid="agent-chat-toggle-email-updates"
                                        aria-label="Allow email updates"
                                    />
                                </div>
                            </div>
                        </section>

                        {/* Advanced — collapsible, closed by default. Holds the knobs most
              users don't touch in a chat session (system prompt, temperature,
              conversation key for multi-user routing). */}
                        <details
                            data-testid="agent-chat-advanced-section"
                            className="group"
                        >
                            <summary className="flex items-center gap-2 cursor-pointer text-[11px] uppercase tracking-wider text-muted-foreground dark:text-zinc-500 hover:text-foreground/80 select-none list-none transition-colors">
                                <svg
                                    className="w-3 h-3 transition-transform group-open:rotate-90"
                                    viewBox="0 0 12 12"
                                    fill="none"
                                    stroke="currentColor"
                                    strokeWidth="2"
                                >
                                    <polyline points="4 2 8 6 4 10" />
                                </svg>
                                Advanced
                            </summary>

                            <div className="mt-3 space-y-5">
                                {/* System prompt. */}
                                <section>
                                    <label className="block text-[11px] uppercase tracking-wider text-muted-foreground dark:text-zinc-500 mb-2">
                                        System Prompt
                                    </label>
                                    <textarea
                                        value={systemPrompt}
                                        onChange={(e) =>
                                            patchConfig({
                                                system_prompt: e.target.value,
                                            })
                                        }
                                        placeholder="You are a helpful assistant."
                                        rows={8}
                                        disabled={isReadOnly}
                                        className="w-full resize-none rounded-lg border border-border bg-sunken text-sm text-foreground placeholder:text-[hsl(var(--placeholder))] leading-relaxed px-3 py-2.5 outline-none focus:border-border dark:focus:border-zinc-700 scrollbar-subtle"
                                    />
                                </section>

                                {/* Temperature. */}
                                <section>
                                    <div className="flex items-center justify-between mb-2">
                                        <label className="block text-[11px] uppercase tracking-wider text-muted-foreground dark:text-zinc-500">
                                            Temperature
                                        </label>
                                        <span className="text-xs text-muted-foreground tabular-nums">
                                            {temperature.toFixed(2)}
                                        </span>
                                    </div>
                                    <input
                                        type="range"
                                        min={0}
                                        max={2}
                                        step={0.05}
                                        value={temperature}
                                        onChange={(e) =>
                                            patchConfig({
                                                temperature: Number(
                                                    e.target.value
                                                ),
                                            })
                                        }
                                        disabled={isReadOnly}
                                        className="w-full accent-foreground"
                                    />
                                    <div className="flex justify-between text-[10px] text-muted-foreground/70 dark:text-zinc-600 mt-1">
                                        <span>focused</span>
                                        <span>creative</span>
                                    </div>
                                </section>

                                {/* Conversation key — multi-user routing (e.g.
                  {{telegram.chat_id}} keeps separate histories per sender). */}
                                <section data-testid="agent-chat-conversation-key-section">
                                    <label className="block text-[11px] uppercase tracking-wider text-muted-foreground dark:text-zinc-500 mb-2">
                                        Conversation Key
                                    </label>
                                    <textarea
                                        value={
                                            (config.conversation_key as
                                                | string
                                                | undefined) ?? ''
                                        }
                                        onChange={(e) =>
                                            patchConfig({
                                                conversation_key:
                                                    e.target.value,
                                            })
                                        }
                                        placeholder="__interface_chat__"
                                        rows={2}
                                        disabled={isReadOnly}
                                        className="w-full resize-none rounded-lg border border-border bg-sunken text-sm text-foreground placeholder:text-[hsl(var(--placeholder))] leading-relaxed px-3 py-2 outline-none focus:border-border dark:focus:border-zinc-700 scrollbar-subtle font-mono"
                                    />
                                    <p className="text-[10px] text-muted-foreground/70 dark:text-zinc-600 mt-1.5 leading-relaxed">
                                        Same key = same conversation. Use refs
                                        like{' '}
                                        <code className="px-1 py-0.5 rounded bg-card text-muted-foreground">
                                            {'{{telegram.chat_id}}'}
                                        </code>{' '}
                                        to keep separate histories per upstream
                                        value.
                                    </p>
                                </section>
                            </div>
                        </details>
                    </div>
                </aside>
            )}

            {onCredentialIdsChange ? (
                <AgentCredentialDialog
                    open={credDialogOpen}
                    onOpenChange={setCredDialogOpen}
                    config={config as Record<string, unknown>}
                    credentialIds={credentialIds ?? {}}
                    onCredentialIdsChange={onCredentialIdsChange}
                />
            ) : null}

            {workflowId ? (
                <AgentShareDialog
                    isOpen={shareOpen}
                    onOpenChange={setShareOpen}
                    workflowId={workflowId}
                    nodeId={id}
                    agentLabel={agentLabel}
                />
            ) : null}

            <WorkspaceFilePreviewDialog
                request={workspacePreview}
                state={workspaceFiles}
                onClose={() => setWorkspacePreview(null)}
                onRetry={() => {
                    void refreshWorkspaceFiles();
                }}
            />
        </div>
    );
}
