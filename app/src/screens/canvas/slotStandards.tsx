// What stands in the canvas's slots (slots.ts) when no host fills them: each works over the platform API alone, with
// the client a `ClientProvider` above gives, or says where on NoClick the thing is done and opens it there, never a gap.
// The SDK loads with the first call (standardsSdk.ts).
import { lazy, Suspense, useContext, useMemo, useSyncExternalStore, type ReactNode } from 'react';
import { ArrowUpRight, LayoutGrid, MessageCircle, Share2 } from 'lucide-react';
import type { Node } from '@xyflow/react';
import type { NoClick, StepType } from 'noclick';
import { useClient } from '@/sdk/client';
import { ConsoleContext } from '@/screens/console/hooks/useConsole';
import { NOCLICK_SITE, workflowUrl } from '@/screens/console/lib/site';
import { BUTTON_GHOST, BUTTON_PRIMARY, BUTTON_SECONDARY } from '@/ui/buttons';
import { DIALOG_MARK, ShellDialog } from '@/ui/ShellDialog';
import { cn } from '@/ui/utils';
import { buildSaveConfig } from './applyNodeUpdate';
import { useStepScope, type StepReads, type StepScope } from './form/reads';
import { displayStrategyOf } from './form/strategyDefaults';
import type { NodeDisplayStrategy } from './form/referenceTypes';
import type { Presence } from './presence';
import type { CanvasBlockProps, CanvasBuilderProps, CanvasInterfaceProps, CanvasPaletteProps, CanvasPresence, CanvasShareProps, StepSchemaRead, Track } from './slots';
import { withoutSecrets } from './stepSecrets';

/** NoClick's own site, as the console the canvas is drawn in names it (a canvas outside one links to noclick.com). */
function useSite(): string {
    return useContext(ConsoleContext)?.site ?? NOCLICK_SITE;
}

const external = { target: '_blank', rel: 'noopener noreferrer' } as const;

// ── the builder chat ────────────────────────────────────────────────────────

// Loaded with the first one drawn: it carries the platform client, which a host that fills the slot never needs.
const BuilderPanel = lazy(() => import('./BuilderPanel'));

/** A build of the workflow from what's asked for, over the platform API (BuilderPanel.tsx). */
export function BuildWithNoClick(props: CanvasBuilderProps) {
    return (
        <Suspense fallback={null}>
            <BuilderPanel {...props} />
        </Suspense>
    );
}

// ── other people on the canvas ──────────────────────────────────────────────

const nothing = () => undefined;

/** Nobody else here, ever: one value, so what reads it never changes. */
const ALONE: Presence = {
    collaborators: [],
    nodeSelections: new Map(),
    updateLocalCursor: nothing,
    updateLocalSelection: nothing,
    broadcastNodeDrag: nothing,
    broadcastNodeAdd: nothing,
    broadcastNodeRemove: nothing,
    broadcastNodeUpdate: nothing,
    broadcastEdgeAdd: nothing,
    broadcastEdgeRemove: nothing,
    broadcastAiEditingStart: nothing,
    broadcastAiEditingUpdate: nothing,
    broadcastAiEditingEnd: nothing,
};

function JustTheSteps({ children }: { children: ReactNode }) {
    return <>{children}</>;
}

/** No one else drawn on the canvas, and nothing this person does sent anywhere until it's saved. */
export const NOBODY_ELSE: CanvasPresence = {
    usePresence: () => ALONE,
    Layer: JustTheSteps,
    Cursors: () => null,
    Avatars: () => null,
};

// ── the Interface tab ───────────────────────────────────────────────────────

/** Where something about the workflow is done on NoClick, with the way there. */
function OnNoClick({ mark, title, line, workflowId, action }: { mark: ReactNode; title: string; line: string; workflowId?: string | null; action: string }) {
    const site = useSite();
    return (
        <div className="flex max-w-[400px] flex-col items-center gap-3 text-center">
            <span className={DIALOG_MARK}>{mark}</span>
            <h2 className="text-[15px] font-semibold text-foreground">{title}</h2>
            <p className="text-[14px] leading-relaxed text-muted-foreground">{line}</p>
            {workflowId && (
                <a href={workflowUrl(site, workflowId)} {...external} className={cn(BUTTON_SECONDARY, 'mt-1')}>
                    {action}
                    <ArrowUpRight className="h-3.5 w-3.5" />
                </a>
            )}
        </div>
    );
}

/** The Interface tab where no host lays it out: it says the page is laid out and published on NoClick. */
export function InterfaceOnNoClick({ workflowId }: CanvasInterfaceProps) {
    return (
        <div className="flex min-h-0 flex-1 items-center justify-center bg-background p-8" data-testid="canvas-interface-standard">
            <OnNoClick
                mark={<LayoutGrid className="h-5 w-5" />}
                title="The interface is laid out on NoClick"
                line="This automation’s forms, tables and chats are arranged into a page, and published, in NoClick’s app."
                workflowId={workflowId}
                action="Open on NoClick"
            />
        </div>
    );
}

// ── an agent's chat ─────────────────────────────────────────────────────────

/** An agent's chat where no host has one: it says the agent is talked to on NoClick. */
export function AgentChatOnNoClick({ config, workflowId }: CanvasBlockProps) {
    const name = typeof config.label === 'string' ? config.label.trim() : '';
    return (
        <div className="flex h-full w-full items-center justify-center p-6" data-testid="canvas-agent-chat-standard">
            <OnNoClick
                mark={<MessageCircle className="h-5 w-5" />}
                title={`Talk to ${name || 'this agent'} on NoClick`}
                line="Its chat, with its model, triggers and tools, is in NoClick’s app."
                workflowId={workflowId}
                action="Open on NoClick"
            />
        </div>
    );
}

// ── sharing ─────────────────────────────────────────────────────────────────

/** Sharing where no host offers it: who else may open the automation is chosen on NoClick. */
export function ShareOnNoClick({ open, onOpenChange, workflow }: CanvasShareProps) {
    const site = useSite();
    return (
        <ShellDialog
            open={open}
            onOpenChange={onOpenChange}
            mark={<Share2 className="h-5 w-5" />}
            title="Share this automation"
            description="Who else may open and edit it is chosen on NoClick, signed in as its owner."
            footer={
                <>
                    <button type="button" className={BUTTON_GHOST} onClick={() => onOpenChange(false)}>
                        Cancel
                    </button>
                    {workflow && (
                        <a href={workflowUrl(site, workflow.id)} {...external} className={BUTTON_PRIMARY}>
                            Share on NoClick
                            <ArrowUpRight className="h-3.5 w-3.5" />
                        </a>
                    )}
                </>
            }
        />
    );
}

// ── a step type's schema: GET /v1/step_types/{type}, once a session ───────────

interface Known {
    read: StepSchemaRead;
    type?: StepType;
    listeners: Set<() => void>;
}

// Per client, so two clients (the app's and a fixture lab's) never mix; kept for the session, since a type's settings
// change only with a release.
const sessions = new WeakMap<NoClick, Map<string, Known>>();

/** Per client: how many of its types have settled, and who hears each one settle (the canvas's drawing, which reads
 *  many types at once). */
const settled = new WeakMap<NoClick, { count: number; listeners: Set<() => void> }>();

function settledOf(client: NoClick) {
    let found = settled.get(client);
    if (!found) settled.set(client, (found = { count: 0, listeners: new Set() }));
    return found;
}

function knownOf(client: NoClick, name: string): Known {
    let types = sessions.get(client);
    if (!types) sessions.set(client, (types = new Map()));
    let known = types.get(name);
    if (!known) {
        const made: Known = { read: { status: 'loading' }, listeners: new Set() };
        types.set(name, (known = made));
        const settle = (read: StepSchemaRead, type?: StepType) => {
            made.read = read;
            made.type = type;
            made.listeners.forEach((listener) => listener());
            const every = settledOf(client);
            every.count += 1;
            every.listeners.forEach((listener) => listener());
        };
        import('./standardsSdk')
            .then(({ stepType }) => stepType(name, { client }))
            .then(
                (type) => settle({ status: 'ready', schema: type.schema }, type),
                (error: unknown) => settle({ status: 'failed', message: `This step’s settings couldn’t be read: ${error instanceof Error ? error.message : String(error)}` })
            );
    }
    return known;
}

/** The type as `GET /v1/step_types/{type}` described it, once read this session. */
export function knownStepType(client: NoClick, name: string): StepType | undefined {
    return sessions.get(client)?.get(name)?.type;
}

/** The type as `GET /v1/step_types/{type}` described it, starting that read this session if it hasn't begun; undefined
 *  until it lands (and for a type the API doesn't describe). `useStepTypesSettled` draws again as each lands. */
export function readStepType(client: NoClick, name: string): StepType | undefined {
    return knownOf(client, name).type;
}

/** How many step types have settled for this client so far, drawing again each time another does. */
export function useStepTypesSettled(client: NoClick): number {
    const every = settledOf(client);
    return useSyncExternalStore(
        (listener) => {
            every.listeners.add(listener);
            return () => void every.listeners.delete(listener);
        },
        () => every.count,
        () => every.count
    );
}

export function useV1StepSchema(type: string): StepSchemaRead {
    const client = useClient();
    const known = knownOf(client, type);
    return useSyncExternalStore(
        (listener) => {
            known.listeners.add(listener);
            return () => void known.listeners.delete(listener);
        },
        () => known.read,
        () => known.read
    );
}

// ── a step's reads, on /v1 ─────────────────────────────────────────────────

function v1StepReads(client: NoClick, scope: StepScope | null): StepReads {
    const step = async () => {
        if (!scope?.workflowId || !scope.nodeId) throw new Error('A step’s fields read through its workflow and step: draw them inside its form.');
        const { Workflow } = await import('./standardsSdk');
        return Workflow.fromId(scope.workflowId, { client }).step(scope.nodeId);
    };
    const options: StepReads['options'] = async (request) => {
        const page = await (await step()).options(request.field_key ?? request.field_name, {
            settings: request.context ?? undefined,
            search: request.search,
            pageToken: request.page_token,
            // The step as the form holds it: one not saved yet lists its choices by its type, through the account its
            // form holds.
            type: request.node_type,
            connection: request.credential_id || undefined,
        });
        // A dropdown stores and shows text: the API's choices are the loader's own, values and labels as it gave them.
        return {
            success: true,
            options: page.options.map((o) => ({ value: String(o.value ?? ''), label: String(o.label ?? o.value ?? ''), metadata: o.metadata })),
            next_page_token: page.nextPageToken,
        };
    };
    return {
        options,
        // The API lists these as the step's own choices too, by the loader's field.
        lookup: options,
        value: async (request) => {
            const loaded = await (await step()).value(request.field_name, { settings: request.context });
            return { success: true, value: loaded.value ?? undefined, values: loaded.values ?? undefined };
        },
        validate: null,
        previewExpression: async (request) => {
            const preview = await (await step()).previewExpression(request.expression, { samples: request.sample_outputs as Record<string, never> });
            const tokens = preview.raw.preview_tokens;
            return {
                ok: preview.ok,
                kind: preview.kind ?? undefined,
                keys: preview.keys,
                preview: preview.preview ?? undefined,
                preview_tokens: Array.isArray(tokens) ? (tokens as Array<{ t: string; v: string }>) : undefined,
                error: preview.error ?? undefined,
            };
        },
        clearState: async () => {
            await (await step()).clearState();
            return { success: true };
        },
        reconnectWebhookRelay: null,
    };
}

export function useV1StepReads(): StepReads {
    const client = useClient();
    const scope = useStepScope();
    const workflowId = scope?.workflowId;
    const nodeId = scope?.nodeId;
    return useMemo(() => v1StepReads(client, { workflowId, nodeId }), [client, workflowId, nodeId]);
}

export function useV1WorkflowId(): string | undefined {
    return useStepScope()?.workflowId;
}

// ── the step form's other standards ───────────────────────────────────────

export function standardDisplayStrategy(): NodeDisplayStrategy {
    return displayStrategyOf(undefined);
}

/** Whether the step still needs an account, from what `GET /v1/step_types/{type}` said of the type (read before the
 *  form drew): its connection, and whether its operation needs an account. */
export function useV1ConnectionMissing(type: string, credentialIds: Record<string, string>, step: { operation?: string }): boolean {
    const known = knownStepType(useClient(), type);
    const connection = known?.connection;
    if (!connection) return false;
    const operation = step.operation ? known.operations.find((op) => op.name === step.operation) : undefined;
    if (operation ? !operation.needsAccount : !connection.needed) return false;
    return !connection.credentialTypes.some((credentialType) => Boolean(credentialIds[credentialType]));
}

const noTrack: Track = () => undefined;

export function useNoTrack(): Track {
    return noTrack;
}

/** The step on NoClick's own canvas, where this app has none of its own yet. */
export function noclickStepLink(workflowId: string, nodeId: string, fieldKey?: string): string {
    const url = new URL('/dashboard', NOCLICK_SITE);
    url.searchParams.set('tab', 'workflows');
    url.searchParams.set('workflow', workflowId);
    url.searchParams.set('node', nodeId);
    if (fieldKey) url.searchParams.set('field', fieldKey);
    return url.toString();
}

// ── adding a step ───────────────────────────────────────────────────────────

// Loaded when the palette first opens: it lists the platform's step types with the client.
const StepPalette = lazy(() => import('./surface/StepPalette'));

/** Every kind of step the platform lists, searched by name or by what it does (surface/StepPalette.tsx). */
export function PaletteOfStepTypes(props: CanvasPaletteProps) {
    return (
        <Suspense fallback={null}>
            <StepPalette {...props} />
        </Suspense>
    );
}

// ── the clipboard ───────────────────────────────────────────────────────────

/** A step's settings as a copy carries them: what it holds, without its secrets. Its type's schema, where this
 *  session has read it, says which settings are secrets beyond what their names say. */
export function useSettingsWithoutSecrets(): (node: Node) => Record<string, unknown> {
    const client = useClient();
    return useMemo(() => (node: Node) => withoutSecrets(buildSaveConfig(node), node.type ? knownStepType(client, node.type)?.schema : undefined), [client]);
}
