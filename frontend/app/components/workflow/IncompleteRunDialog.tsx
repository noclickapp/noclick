// Shown when the Run button is pressed on a workflow that still has steps
// missing credentials or required fields. Before this, Run started the workflow
// regardless and it failed partway through with a runtime error.
//
// Laid out as a wizard — one step at a time, with a segmented progress bar you
// can also click to jump around. Chosen over list, table, split-rail and sheet
// alternatives (compared side by side in a scratch gallery, since deleted)
// because a list of every hole at once reads as a wall of problems, while one
// step with one field reads as a task.
//
// The popup is not just a report: every requirement is satisfied WHERE IT IS
// LISTED, using the same controls the config panel renders — fields via
// NodeConfigFieldControl, a tool provider's allowlist via
// AgentToolOperationsPicker, and accounts via NodeCredentials. Credentials
// were the last hand-off to go: clicking Connect closed the popup, which cost
// the user their place and made them press Run again to get back. OAuth now
// opens its provider window with the popup still up, and the block flips to
// Done when the credential lands.
//
// It is a soft gate — the run action is always available, labelled "Run anyway"
// while something is still missing.
import { useState } from 'react';
import {
    AlertCircle,
    ArrowRight,
    Box,
    Check,
    Play,
    Settings2,
} from 'lucide-react';
import {
    Dialog,
    DialogContent,
    DialogTitle,
    DialogDescription,
} from '~/components/ui/dialog';
import { Checkbox } from '~/components/ui/checkbox';
import { SerializedIcon } from '~/components/shared/SerializedIcon';
import { NodeConfigFieldControl } from './NodeConfig';
import { NodeCredentials } from './NodeCredentials';
import type { CredentialDisplayMeta } from '~/utils/credentialAutoSelect';
import { AgentToolOperationsPicker } from './AgentToolOperationsPicker';
import { NodeOperationPicker } from './NodeOperationPicker';
import {
    TOOL_OPERATIONS_KEY,
    type IncompleteStep,
    type RunPath,
} from '~/utils/incompleteRunPrompt';

interface IncompleteRunDialogProps {
    steps: IncompleteStep[];
    /** Entry points this run can start from. One is not a choice, so the
     *  chooser only appears for two or more (or for a lone agent, which still
     *  wants its opening message). */
    paths: RunPath[];
    /** Entry points currently ticked. */
    selectedPathIds: Set<string>;
    onTogglePath: (nodeId: string, selected: boolean) => void;
    /** Tick every entry point, or clear them all when any are ticked. */
    onToggleAllPaths: () => void;
    /** Opening message per agent entry point, prefilled from its saved
     *  message. One-shot: edits here do not rewrite the node. */
    pathMessages: Record<string, string>;
    onPathMessageChange: (nodeId: string, message: string) => void;
    /** Whether running a lone agent takes the user to its chat. True for a
     *  whole-workflow run; a node-scoped one leaves them on the canvas. */
    handsOffToChat: boolean;
    /** Current config values, by node id — the inline editors are controlled. */
    valuesForNode: (nodeId: string) => Record<string, unknown>;
    /** Credential ids by node id, needed by dynamic-options dropdowns. */
    credentialsForNode: (nodeId: string) => Record<string, string>;
    workflowId?: string;
    /** Write one field back to the node. */
    onFieldChange: (nodeId: string, fieldKey: string, value: unknown) => void;
    /** Pick the node's action (the discriminator). Separate from onFieldChange
     *  because the operation is top-level node metadata, not a config field. */
    onOperationChange: (nodeId: string, operation: string) => void;
    /** Apply a credential pick — must go through applyCredentialSelection so the
     *  run-as-owner authorization goes with it. */
    onCredentialsChange: (
        nodeId: string,
        credentialIds: Record<string, string>,
        credentialMeta?: Record<string, CredentialDisplayMeta>,
        credentialRemoved?: string[]
    ) => void;
    /** Close the popup (via the X button, Escape, or clicking the backdrop). */
    onClose: () => void;
    /** Open a step's config panel (selects it, expands the config view). */
    onOpenStepConfig: (nodeId: string) => void;
    /** Open a step's Credentials tab full screen — connecting an account needs
     *  more room than the config sheet gives. */
    onOpenStepCredentials: (nodeId: string) => void;
    /** Run the workflow. Labelled "Run anyway" while anything is still missing. */
    onRun: () => void;
}

/**
 * One requirement, in the anatomy every requirement uses: NAME, its state, a
 * line saying what is wanted, then the control that satisfies it.
 *
 * The three kinds — a missing field, a missing credential, an empty tool
 * allowlist — used to be drawn three different ways: a labelled input, an amber
 * sentence with a button, and a bare list under a heading. Same idea, three
 * looks, and the list in particular arrived with nothing saying why it was
 * there. Routing them all through here is what makes "what is being asked of
 * me" answerable without reading prose.
 */
function Requirement({
    name,
    hint,
    done,
    children,
    ...rest
}: {
    name: string;
    hint?: string;
    done: boolean;
    children: React.ReactNode;
} & React.HTMLAttributes<HTMLDivElement>) {
    return (
        // A filled block, not a run of text: several requirements stacked as
        // bare label/hint/control read as one continuous column, so where one
        // ended and the next began had to be inferred from spacing. The whole
        // surface carries the state — amber while outstanding, neutral once met
        // — which is the same signal the canvas pill and the step icon use.
        <div
            className={`rounded-xl p-3.5 ring-1 ring-inset transition-colors ${
                done
                    ? 'bg-foreground/[0.02] ring-foreground/[0.07]'
                    : // Definition comes from an OPAQUE border, not a strong
                      // fill. A translucent ring over a pale tint read as washed
                      // out; answering that with saturation instead turned a
                      // block containing a 14-row picker into a highlighter,
                      // with the list's own white group strips fighting it. The
                      // standard light callout is a near-white tint plus a solid
                      // border, which stays legible at any block height.
                      'bg-amber-50 ring-amber-300 dark:bg-amber-500/[0.07] dark:ring-amber-500/25'
            }`}
            {...rest}
        >
            <div className="flex items-center gap-2">
                {/* Solid, not translucent: over a saturated fill a
                    part-transparent near-black mixes toward the amber and goes
                    muddy, which is most of what "washed out" was. */}
                <span className="text-[12px] font-semibold uppercase tracking-wide text-foreground">
                    {name}
                </span>
                {done ? (
                    <span className="inline-flex items-center gap-1 text-[11px] font-semibold uppercase tracking-wide text-emerald-700 dark:text-emerald-400">
                        <Check className="h-3.5 w-3.5" />
                        Done
                    </span>
                ) : (
                    <span className="text-[11px] font-semibold uppercase tracking-wide text-amber-900 dark:text-amber-400/90">
                        Required
                    </span>
                )}
            </div>
            {/* The hint is the instruction, not a caption — it carries the
                "at least one" rule for the actions list, and what an account is
                being connected for. At muted-foreground/12.5px it read as fine
                print and got skipped, so it sits a step up in both size and
                contrast from the surrounding secondary text. */}
            {hint && (
                <p className="mt-1 text-[13.5px] leading-snug text-foreground/90">
                    {hint}
                </p>
            )}
            <div className="mt-2">{children}</div>
        </div>
    );
}

/** "Slack, Gmail + 2 more" — enough of a branch to recognise it without
 *  turning the row into a list. */
function summarise(names: string[], max = 2): string {
    if (names.length <= max) return names.join(', ');
    return `${names.slice(0, max).join(', ')} + ${names.length - max} more`;
}

/** The agent's opening line for this run. Autosized because the saved message
 *  is often a paragraph of standing instructions, and a 2-row box asking you to
 *  edit it while showing a third of it is the wrong end of the trade. */
function MessageBox({
    nodeId,
    value,
    onChange,
    rows,
}: {
    nodeId: string;
    value: string;
    onChange: (nodeId: string, message: string) => void;
    rows: number;
}) {
    return (
        <textarea
            data-run-path-message={nodeId}
            rows={rows}
            value={value}
            onChange={(e) => onChange(nodeId, e.target.value)}
            placeholder="What should the agent do?"
            // resize-none on purpose: the grabber is the loudest thing in an
            // otherwise empty box. Ring rather than border so the field sits at
            // the same weight as the card around it instead of outranking it.
            className="w-full resize-none rounded-lg bg-foreground/[0.03] px-3 py-2 text-[13.5px] leading-relaxed text-foreground ring-1 ring-inset ring-foreground/[0.09] transition-shadow placeholder:text-muted-foreground/50 focus:outline-none focus:ring-foreground/25 dark:bg-black/20"
        />
    );
}

/** The tick that marks an entry point in or out. Presentational — its ROW is
 *  the control, so it is hidden from AT rather than read as a nested one. */
function PathTick({ selected }: { selected: boolean }) {
    return (
        <Checkbox
            checked={selected}
            tabIndex={-1}
            aria-hidden
            data-run-path-box
            className="pointer-events-none h-4 w-4 shrink-0 rounded-[5px] border-muted-foreground/40 data-[state=checked]:border-primary data-[state=checked]:bg-primary data-[state=checked]:text-primary-foreground dark:border-white/25 [&_svg]:h-3 [&_svg]:w-3"
        />
    );
}

function PathIcon({ path, on }: { path: RunPath; on: boolean }) {
    return (
        <span
            className={`flex h-5 w-5 shrink-0 items-center justify-center transition-opacity ${
                on ? '' : 'opacity-45 grayscale'
            }`}
        >
            {path.iconHtml ? (
                <SerializedIcon
                    html={path.iconHtml}
                    iconColor={path.iconColor}
                    className="h-[18px] w-[18px]"
                />
            ) : (
                <Box
                    className="h-[18px] w-[18px] text-muted-foreground/70"
                    strokeWidth={1.75}
                />
            )}
        </span>
    );
}

/** "Then Slack, Gmail · Uses Telegram", or what to say when there is neither. */
function pathSummary(path: RunPath): string {
    const parts = [
        path.downstream.length > 0 ? `Then ${summarise(path.downstream)}` : '',
        path.tools.length > 0 ? `Uses ${summarise(path.tools)}` : '',
    ].filter(Boolean);
    // "Runs on its own" beats an empty line: silence there reads as missing
    // information rather than as the answer.
    return parts.join(' · ') || 'Runs on its own';
}

/**
 * Which entry points this run starts from, and what an agent entry point is
 * asked to do.
 *
 * The agent leads. Its message is the only thing on this screen anyone has to
 * WRITE — everything else is a tick — and burying it inside one card of a
 * uniform list made the screen read as a list of checkboxes that happened to
 * contain a text box. Other branches follow under "Also run", which is what
 * they are: things that also happen, not things you came here to decide.
 *
 * The shapes fall out of the data rather than being special-cased. One agent
 * and nothing else collapses to a bare message box — with a single entry point
 * there is nothing to tick, and a lone always-checked box reads as broken. No
 * agent at all leaves just the list, with no heading to introduce it, because
 * then the list IS the screen.
 */
function PathChooser({
    paths,
    selectedIds,
    onToggle,
    messages,
    onMessageChange,
    handsOffToChat,
}: {
    paths: RunPath[];
    selectedIds: Set<string>;
    onToggle: (nodeId: string, selected: boolean) => void;
    messages: Record<string, string>;
    onMessageChange: (nodeId: string, message: string) => void;
    handsOffToChat: boolean;
}) {
    const agents = paths.filter((p) => p.isAgent);
    const others = paths.filter((p) => !p.isAgent);
    // With one entry point there is nothing to leave out.
    const choosable = paths.length > 1;

    return (
        <div data-run-paths>
            {agents.map((agent, i) => {
                const on = selectedIds.has(agent.nodeId);
                const open = on || !choosable;
                // Mirrors startSelectedRunPaths: the chat handoff happens only
                // when this agent IS the run — the lone selection on a whole-
                // workflow Run. With another branch ticked, the run rides
                // workflow:execute and the user stays on the canvas, so
                // promising an opening chat would be a lie.
                const opensChat =
                    handsOffToChat &&
                    (!choosable || (on && selectedIds.size === 1));
                return (
                    <div
                        key={agent.nodeId}
                        data-run-path={agent.nodeId}
                        data-run-path-selected={on ? 'true' : 'false'}
                        className={i > 0 ? 'mt-4' : ''}
                    >
                        {choosable && (
                            <button
                                type="button"
                                role="checkbox"
                                aria-checked={on}
                                onClick={() => onToggle(agent.nodeId, !on)}
                                className="mb-2 flex w-full items-center gap-2.5 rounded-lg py-1 text-left"
                            >
                                <PathIcon path={agent} on={on} />
                                <span
                                    className={`truncate text-[13.5px] font-medium transition-colors ${
                                        on
                                            ? 'text-foreground'
                                            : 'text-muted-foreground'
                                    }`}
                                >
                                    {agent.title}
                                </span>
                                {agent.label && agent.label !== agent.title && (
                                    <span className="shrink-0 truncate rounded-full bg-foreground/[0.06] px-1.5 py-px text-[10.5px] text-muted-foreground">
                                        {agent.label}
                                    </span>
                                )}
                                <span className="ml-auto shrink-0">
                                    <PathTick selected={on} />
                                </span>
                            </button>
                        )}
                        {open && (
                            <>
                                <MessageBox
                                    nodeId={agent.nodeId}
                                    value={messages[agent.nodeId] ?? ''}
                                    onChange={onMessageChange}
                                    rows={choosable ? 4 : 5}
                                />
                                <p className="mt-2 text-[12.5px] leading-snug text-muted-foreground">
                                    {[
                                        opensChat
                                            ? 'Answers in the chat, which opens as soon as the run starts'
                                            : 'Answers on the node',
                                        agent.tools.length > 0
                                            ? `can use ${summarise(agent.tools, 3)}`
                                            : '',
                                    ]
                                        .filter(Boolean)
                                        .join(', ') + '.'}
                                </p>
                            </>
                        )}
                    </div>
                );
            })}

            {others.length > 0 && (
                <div
                    className={
                        agents.length > 0
                            ? 'mt-4 border-t border-foreground/[0.07] pt-3'
                            : ''
                    }
                >
                    {/* Only when there is something above it to be "also". */}
                    {agents.length > 0 && (
                        <div className="mb-1 text-[11.5px] font-semibold uppercase tracking-wide text-muted-foreground">
                            Also run
                        </div>
                    )}
                    {others.map((path) => {
                        const on = selectedIds.has(path.nodeId);
                        return (
                            <div
                                key={path.nodeId}
                                data-run-path={path.nodeId}
                                data-run-path-selected={on ? 'true' : 'false'}
                            >
                                <button
                                    type="button"
                                    role="checkbox"
                                    aria-checked={on}
                                    onClick={() => onToggle(path.nodeId, !on)}
                                    className="flex w-full items-center gap-2.5 rounded-lg px-1 py-2 text-left transition-colors hover:bg-foreground/[0.03]"
                                >
                                    <PathIcon path={path} on={on} />
                                    <span
                                        className={`shrink-0 truncate text-[13.5px] transition-colors ${
                                            on
                                                ? 'font-medium text-foreground'
                                                : 'text-muted-foreground'
                                        }`}
                                    >
                                        {path.title}
                                    </span>
                                    {path.label &&
                                        path.label !== path.title && (
                                            <span className="shrink-0 truncate rounded-full bg-foreground/[0.06] px-1.5 py-px text-[10.5px] text-muted-foreground">
                                                {path.label}
                                            </span>
                                        )}
                                    <span className="ml-auto min-w-0 truncate pl-3 text-right text-[11.5px] text-muted-foreground">
                                        {pathSummary(path)}
                                    </span>
                                    {choosable && <PathTick selected={on} />}
                                </button>
                            </div>
                        );
                    })}
                </div>
            )}
        </div>
    );
}

/** One segment per screen, coloured by state and clickable to jump. Hidden for
 *  a single screen, where a one-segment bar and "Step 1 of 1" are just noise.
 *  Takes plain segments rather than steps so the entry-point screen — which is
 *  not a step but is a screen — gets a segment like everything else. */
function StepProgress({
    segments,
    index,
    onJump,
}: {
    segments: { key: string; title: string; resolved: boolean }[];
    index: number;
    onJump: (i: number) => void;
}) {
    return (
        <div className="flex gap-1.5">
            {segments.map((segment, i) => (
                <button
                    key={segment.key}
                    type="button"
                    onClick={() => onJump(i)}
                    aria-label={`Go to ${segment.title}`}
                    aria-current={i === index ? 'step' : undefined}
                    className="group flex-1 py-1.5"
                >
                    {/* Amber for every outstanding step, not just the one you
                        are on. Colouring only the current one left the ones you
                        had paged past looking identical to the ones that are
                        fine, so the bar disagreed with the "N nodes need setup"
                        count right above it. The current step is the brighter
                        one of its colour. */}
                    <span
                        className={`block h-1 rounded-full transition-colors ${
                            segment.resolved
                                ? i === index
                                    ? 'bg-emerald-500'
                                    : 'bg-emerald-500/40'
                                : i === index
                                  ? 'bg-amber-500'
                                  : 'bg-amber-500/35 group-hover:bg-amber-500/60'
                        }`}
                    />
                </button>
            ))}
        </div>
    );
}

// The parent mounts this only while open and unmounts it to close, rather than
// toggling Radix's `open` prop — same reasoning as TriggerInfoDialog (a
// prefers-reduced-motion quirk can strand the exit animation, leaving the body
// pointer-events lock on).
export function IncompleteRunDialog({
    steps,
    paths,
    selectedPathIds,
    onTogglePath,
    onToggleAllPaths,
    pathMessages,
    onPathMessageChange,
    handsOffToChat,
    valuesForNode,
    credentialsForNode,
    workflowId,
    onFieldChange,
    onOperationChange,
    onCredentialsChange,
    onClose,
    onOpenStepConfig,
    onOpenStepCredentials,
    onRun,
}: IncompleteRunDialogProps) {
    const [rawIndex, setRawIndex] = useState(0);
    // One entry point is not a choice — but a lone agent still wants its
    // opening message, which is the other reason this screen exists.
    const showPaths = paths.length > 1 || paths.some((p) => p.isAgent);
    const nothingSelected = paths.length > 0 && selectedPathIds.size === 0;

    // The chooser is the LAST screen, after the setup it depends on: what to
    // run is the decision you make once the steps it would run are fixed, and
    // as a permanent band above them it competed with the step for the eye on
    // every page.
    const screens = steps.length + (showPaths ? 1 : 0);
    // Clamped rather than stored clamped: a collaborator can delete a step while
    // the popup is open, and an out-of-range index would blank the body.
    const index = Math.min(rawIndex, Math.max(screens - 1, 0));
    const onPaths = showPaths && index === steps.length;
    const step: IncompleteStep | undefined = onPaths ? undefined : steps[index];
    const remaining = steps.filter((s) => !s.resolved).length;
    const allReady = remaining === 0;
    const multiple = screens > 1;
    // >= not ==: with no screens at all index is 0 and screens-1 is -1, and an
    // equality test would leave the footer showing Next forever.
    const last = index >= screens - 1;
    const values = step ? valuesForNode(step.nodeId) : {};
    const chosenToolActions = values[TOOL_OPERATIONS_KEY];
    const toolActionsChosen =
        Array.isArray(chosenToolActions) && chosenToolActions.length > 0;

    const loneAgent =
        paths.length === 1 && paths[0].isAgent ? paths[0] : undefined;
    const pathsTitle = loneAgent ? 'Starting message' : 'What to run';
    const segments = [
        ...steps.map((s) => ({
            key: s.nodeId,
            title: s.title,
            resolved: s.resolved,
        })),
        ...(showPaths
            ? [
                  {
                      key: '__paths__',
                      title: pathsTitle,
                      resolved: !nothingSelected,
                  },
              ]
            : []),
    ];

    return (
        <Dialog
            open
            onOpenChange={(o) => {
                if (!o) onClose();
            }}
        >
            <DialogContent
                data-incomplete-run-dialog
                data-step-ids={steps.map((s) => s.nodeId).join(',')}
                data-current-step={step?.nodeId ?? ''}
                data-current-screen={onPaths ? 'paths' : 'step'}
                className={`flex max-h-[85vh] flex-col gap-0 overflow-hidden border-foreground/10 p-0 ${
                    // Widened whenever any step shows an operation list —
                    // the node's own action and a provider's allowlist render
                    // the same picker, so they need the same room. Sized for
                    // the whole popup rather than the step that needs it, since
                    // per-step sizing makes the dialog jump as you page past.
                    steps.some((s) => s.needsToolActions || s.needsOperation)
                        ? 'max-w-xl'
                        : 'max-w-md'
                }`}
            >
                {/* pr-12 keeps the row clear of Radix's absolute close button,
                    which the progress bar used to run underneath. */}
                <div className="shrink-0 px-7 pb-4 pt-6">
                    <div className="flex items-center justify-between gap-3 pr-12">
                        {/* The count IS the message — "2 nodes need setup" says
                            in the pill what a separate sentence used to. */}
                        {steps.length === 0 ? (
                            <span className="inline-flex items-center gap-1.5 rounded-full bg-foreground/[0.06] px-2 py-0.5 text-[11.5px] font-semibold uppercase tracking-wide text-foreground/70">
                                <Play className="h-3 w-3" fill="currentColor" />
                                Before running
                            </span>
                        ) : allReady ? (
                            <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-500/10 px-2 py-0.5 text-[11.5px] font-semibold uppercase tracking-wide text-emerald-700 ring-1 ring-inset ring-emerald-500/25 dark:text-emerald-400">
                                <Check className="h-3 w-3" />
                                Ready to run
                            </span>
                        ) : (
                            <span className="inline-flex items-center gap-1.5 rounded-full bg-amber-400/20 px-2 py-0.5 text-[11.5px] font-semibold uppercase tracking-wide text-amber-800 ring-1 ring-inset ring-amber-500/30 dark:bg-amber-400/10 dark:text-amber-300">
                                <AlertCircle className="h-3 w-3" />
                                {remaining === 1
                                    ? '1 node needs setup'
                                    : `${remaining} nodes need setup`}
                            </span>
                        )}
                        {multiple && (
                            <span className="shrink-0 text-[12px] font-medium text-muted-foreground">
                                Step {index + 1} of {screens}
                            </span>
                        )}
                    </div>

                    {multiple && (
                        <div className="mt-3">
                            <StepProgress
                                segments={segments}
                                index={index}
                                onJump={setRawIndex}
                            />
                        </div>
                    )}

                    {/* sr-only: the Requirement blocks below each name what they
                        want and mark it REQUIRED, so a header sentence saying
                        the same thing in prose was a line to skip past. Kept in
                        the tree because Radix wants a described-by target and a
                        screen reader has no equivalent of scanning the blocks. */}
                    <DialogDescription className="sr-only">
                        {steps.length === 0
                            ? 'Choose which parts of this workflow to run.'
                            : allReady
                              ? 'Everything is set up — this workflow is ready to run.'
                              : `Run can't start yet: ${remaining} of ${steps.length} steps still need setup.`}
                    </DialogDescription>
                </div>

                {/* Radix wants a title in the tree on every screen. */}
                {!step && !onPaths && (
                    <DialogTitle className="sr-only">
                        Before running
                    </DialogTitle>
                )}

                {onPaths && (
                    <>
                        {/* Same header/body anatomy as a step screen — this is
                            one more page of the wizard, not a different kind
                            of thing. With one agent the header names IT, since
                            that is the thing the message below belongs to. */}
                        <div className="flex shrink-0 items-center gap-3 border-t border-foreground/[0.06] px-7 py-3.5">
                            {/* Only when it identifies something. On the step
                                screens the icon says WHICH node; a generic play
                                glyph here says nothing the title does not. */}
                            {loneAgent?.iconHtml && (
                                <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-foreground/[0.05]">
                                    <SerializedIcon
                                        html={loneAgent.iconHtml}
                                        iconColor={loneAgent.iconColor}
                                        className="h-[20px] w-[20px]"
                                    />
                                </span>
                            )}
                            <div className="min-w-0 flex-1">
                                <DialogTitle className="truncate text-[17px] font-semibold tracking-tight text-foreground">
                                    {pathsTitle}
                                </DialogTitle>
                                <p className="truncate text-[12.5px] text-muted-foreground">
                                    {loneAgent
                                        ? loneAgent.label || loneAgent.title
                                        : `${selectedPathIds.size} of ${paths.length} selected`}
                                </p>
                            </div>
                            {/* Only worth a control when ticking them one by one
                                would be tedious. */}
                            {paths.length > 2 && (
                                <button
                                    type="button"
                                    onClick={onToggleAllPaths}
                                    className="shrink-0 rounded-md px-2 py-1 text-[12px] font-medium text-muted-foreground/80 transition-colors hover:bg-foreground/[0.06] hover:text-foreground"
                                >
                                    {nothingSelected ? 'Select all' : 'Clear'}
                                </button>
                            )}
                        </div>

                        <div className="min-h-[124px] flex-1 overflow-y-auto scrollbar-subtle px-7 pb-6 pt-3">
                            <PathChooser
                                paths={paths}
                                selectedIds={selectedPathIds}
                                onToggle={onTogglePath}
                                messages={pathMessages}
                                onMessageChange={onPathMessageChange}
                                handsOffToChat={handsOffToChat}
                            />
                            {nothingSelected && (
                                <p className="mt-3 flex items-center gap-1.5 text-[12.5px] font-medium text-amber-700 dark:text-amber-400">
                                    <AlertCircle className="h-3.5 w-3.5 shrink-0" />
                                    Pick at least one starting point to run.
                                </p>
                            )}
                        </div>
                    </>
                )}

                {step && (
                    <>
                        {/* The node this step is about, with its escape hatch beside the
                    name rather than buried in the footer. */}
                        <div className="flex shrink-0 items-center gap-3 border-t border-foreground/[0.06] px-7 py-3.5">
                            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-foreground/[0.05]">
                                {step.iconHtml ? (
                                    <SerializedIcon
                                        html={step.iconHtml}
                                        iconColor={step.iconColor}
                                        className="h-[20px] w-[20px]"
                                    />
                                ) : (
                                    <Box
                                        className="h-5 w-5 text-muted-foreground/70 dark:text-zinc-500"
                                        strokeWidth={1.75}
                                    />
                                )}
                            </span>
                            <div className="min-w-0 flex-1">
                                <DialogTitle className="truncate text-[17px] font-semibold tracking-tight text-foreground">
                                    {step.title}
                                </DialogTitle>
                                {step.label && step.label !== step.title && (
                                    <p className="truncate text-[12.5px] text-muted-foreground">
                                        {step.label}
                                    </p>
                                )}
                            </div>
                            <button
                                type="button"
                                onClick={() => onOpenStepConfig(step.nodeId)}
                                className="group inline-flex shrink-0 items-center gap-1.5 rounded-md px-2 py-1 text-[12px] font-medium text-muted-foreground/80 transition-colors hover:bg-foreground/[0.06] hover:text-foreground"
                            >
                                <Settings2 className="h-3.5 w-3.5 text-muted-foreground/70 dark:text-zinc-500 transition-colors group-hover:text-muted-foreground dark:group-hover:text-zinc-300" />
                                Open config
                            </button>
                        </div>

                        {/* Body. A floor on the height keeps the popup from resizing as
                    you page between a one-field step and a credentials one; the
                    scroll is for the other end — a step with several required
                    fields plus a credential blocker runs past the viewport. */}
                        <div
                            data-step-node-id={step.nodeId}
                            className="min-h-[124px] flex-1 overflow-y-auto scrollbar-subtle px-7 pb-6 pt-5"
                        >
                            {/* Tighter than the old bare-text stack: the blocks have
                        their own edges now, so they no longer need whitespace
                        to separate them. */}
                            <div className="flex flex-col gap-3">
                                {/* First, because until it is answered nothing else
                            about this step is knowable — which fields it needs
                            depends entirely on the action. */}
                                {step.needsOperation && (
                                    <Requirement
                                        name="Action"
                                        hint={`Pick what this step should do. ${step.title} offers several actions, and which fields it needs depends on the one you choose.`}
                                        done={Boolean(step.operation)}
                                        data-step-operation={step.nodeId}
                                    >
                                        <NodeOperationPicker
                                            nodeType={step.nodeType}
                                            operation={step.operation}
                                            onOperationChange={(value) =>
                                                onOperationChange(
                                                    step.nodeId,
                                                    value
                                                )
                                            }
                                        />
                                    </Requirement>
                                )}

                                {/* Sticky, like every other requirement: once
                                    listed it stays, flipping to Done. Deriving
                                    it from the live blocker made the block —
                                    and with it the whole step body — vanish the
                                    instant an account was connected, leaving
                                    "Nothing left to fill in for this step" on a
                                    step the user had just finished. */}
                                {step.needsCredentials && (
                                    <Requirement
                                        name="Credentials"
                                        hint={`Connect an account so this step can use ${step.title}.`}
                                        done={step.credentialsConnected}
                                        data-step-credentials={step.nodeId}
                                    >
                                        {/* Connected in place rather than handed off.
                                        Every other requirement is satisfied where
                                        it is listed; sending the user to the
                                        config panel for this one closed the popup
                                        and cost them their place, so they had to
                                        press Run again to get back. */}
                                        <NodeCredentials
                                            nodeType={step.nodeType}
                                            nodeData={{
                                                operation: step.operation,
                                                config: values,
                                            }}
                                            credentialIds={credentialsForNode(
                                                step.nodeId
                                            )}
                                            onChange={(ids, meta, removed) =>
                                                onCredentialsChange(
                                                    step.nodeId,
                                                    ids,
                                                    meta,
                                                    removed
                                                )
                                            }
                                            compact
                                        />
                                        <button
                                            type="button"
                                            onClick={() =>
                                                onOpenStepCredentials(
                                                    step.nodeId
                                                )
                                            }
                                            className="mt-2 text-[12px] font-medium text-muted-foreground underline underline-offset-2 transition-colors hover:text-foreground"
                                        >
                                            Open the full credentials panel
                                        </button>
                                    </Requirement>
                                )}

                                {step.blockers.map((blocker, i) => (
                                    <Requirement
                                        key={i}
                                        name="Configuration"
                                        hint={blocker.message}
                                        done={false}
                                    >
                                        <button
                                            type="button"
                                            onClick={() =>
                                                onOpenStepConfig(step.nodeId)
                                            }
                                            className="inline-flex items-center gap-1.5 rounded-lg bg-foreground/10 px-3 py-1.5 text-[13px] font-semibold text-foreground ring-1 ring-inset ring-foreground/15 transition-colors hover:bg-foreground/[0.16]"
                                        >
                                            <Settings2 className="h-3.5 w-3.5" />
                                            Open config
                                        </button>
                                    </Requirement>
                                ))}

                                {step.fields.map((field) => (
                                    <Requirement
                                        key={field.key}
                                        name={
                                            (field.prop.title as string) ||
                                            field.key
                                        }
                                        hint={
                                            field.prop.description as
                                                | string
                                                | undefined
                                        }
                                        done={field.filled}
                                        data-step-field={field.key}
                                        data-field-filled={
                                            field.filled ? 'true' : 'false'
                                        }
                                    >
                                        <NodeConfigFieldControl
                                            fieldKey={field.key}
                                            prop={field.prop}
                                            value={values[field.key] ?? ''}
                                            onChange={(key, value) =>
                                                onFieldChange(
                                                    step.nodeId,
                                                    key,
                                                    value
                                                )
                                            }
                                            nodeType={step.nodeType}
                                            nodeId={step.nodeId}
                                            workflowId={workflowId}
                                            credentialIds={credentialsForNode(
                                                step.nodeId
                                            )}
                                            config={values}
                                            onOpenCredentials={() =>
                                                onOpenStepConfig(step.nodeId)
                                            }
                                        />
                                    </Requirement>
                                ))}

                                {step.needsToolActions && (
                                    <Requirement
                                        name="Actions"
                                        hint={`Pick at least one action the agent is allowed to run with ${step.title}.`}
                                        done={toolActionsChosen}
                                        data-step-tool-actions={step.nodeId}
                                    >
                                        {/* Its own intro is suppressed: this block already
                                    says what the list is and why it is required,
                                    in the same shape as every other requirement. */}
                                        <AgentToolOperationsPicker
                                            nodeType={step.nodeType}
                                            selectedOperations={
                                                (values[TOOL_OPERATIONS_KEY] as
                                                    | string[]
                                                    | undefined) ?? []
                                            }
                                            onChange={(operations) =>
                                                onFieldChange(
                                                    step.nodeId,
                                                    TOOL_OPERATIONS_KEY,
                                                    operations
                                                )
                                            }
                                            hideIntro
                                        />
                                    </Requirement>
                                )}
                            </div>

                            {step.blockers.length === 0 &&
                                step.fields.length === 0 &&
                                !step.needsToolActions && (
                                    <p className="text-[13px] text-muted-foreground">
                                        Nothing left to fill in for this step.
                                    </p>
                                )}
                        </div>
                    </>
                )}

                {/* Navigation sits together on the right — Back is the partner
                    of Next, not of the run action. */}
                <div className="flex shrink-0 items-center justify-end gap-2 border-t border-foreground/[0.06] px-7 pb-6 pt-4">
                    {multiple && (
                        <button
                            type="button"
                            disabled={index === 0}
                            onClick={() => setRawIndex(index - 1)}
                            className="rounded-lg px-3 py-1.5 text-[13px] font-medium text-muted-foreground transition-colors hover:bg-foreground/[0.06] hover:text-foreground disabled:pointer-events-none disabled:opacity-30"
                        >
                            Back
                        </button>
                    )}
                    <div className="flex shrink-0 items-center gap-2">
                        {last ? (
                            <button
                                type="button"
                                onClick={onRun}
                                // Nothing ticked means nothing would happen; a
                                // Run button that silently no-ops is worse than
                                // one that is visibly unavailable.
                                disabled={nothingSelected}
                                title={
                                    nothingSelected
                                        ? 'Pick at least one starting point'
                                        : undefined
                                }
                                className={`${
                                    allReady
                                        ? 'bg-primary text-primary-foreground hover:opacity-90'
                                        : 'bg-foreground/10 text-foreground ring-1 ring-inset ring-foreground/15 hover:bg-foreground/[0.16]'
                                } inline-flex items-center gap-1.5 rounded-lg px-3.5 py-1.5 text-[13px] font-semibold transition-opacity disabled:pointer-events-none disabled:opacity-40`}
                            >
                                <Play
                                    className="h-3.5 w-3.5"
                                    fill="currentColor"
                                />
                                {allReady ? 'Run' : 'Run anyway'}
                            </button>
                        ) : (
                            <button
                                type="button"
                                onClick={() => setRawIndex(index + 1)}
                                className="inline-flex items-center gap-1.5 rounded-lg bg-foreground/10 px-3.5 py-1.5 text-[13px] font-semibold text-foreground ring-1 ring-inset ring-foreground/15 transition-colors hover:bg-foreground/[0.16]"
                            >
                                Next
                                <ArrowRight className="h-3.5 w-3.5" />
                            </button>
                        )}
                    </div>
                </div>
            </DialogContent>
        </Dialog>
    );
}
