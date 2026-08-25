import type { Node, Edge } from '@xyflow/react';
import {
    ListChecks,
    ChevronDown,
    ClipboardList,
    Download,
    FolderOpen,
    Grid,
    LayoutGrid,
    MoreVertical,
    Paintbrush,
    Play,
    Settings,
    Share2,
    Trash2,
    Upload,
    X,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { AppNavbar } from '~/components/ui/AppNavbar';
import { Button } from '~/components/ui/button';
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from '~/components/ui/dropdown-menu';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '~/components/ui/tooltip';
import { KeyHint } from '~/components/shared/KeyHint';
import { useElementWidth } from '~/hooks/useElementWidth';
import { cn } from '~/lib/utils';
import { CollaboratorAvatars } from '../collaboration';
import type { Collaborator } from '~/lib/collaboration';
import { WorkflowCheckpointControl } from '../WorkflowCheckpointControl';

type CanvasTab = 'interface' | 'canvas' | 'logs' | 'resources' | 'setup';
type HelperTabType = 'home' | 'config' | 'credentials' | null;

// Navbar compaction is keyed off the bar's OWN measured width, not the
// viewport — on the canvas the bar is narrowed by the chat drawer and the
// FlowHelperView panel, so a viewport breakpoint mismeasures its real space.
// As the bar tightens, labels drop in two stages: 'medium' iconifies the
// secondary tabs (Logs / Versions / Resources / Setup), then 'compact'
// iconifies the primary tabs (Interface / Workflow) and the right-side
// actions too. Thresholds are the bar widths at which the next group stops
// fitting; tune here if tab labels change.
type NavDensity = 'full' | 'medium' | 'compact';
const NAV_FULL_MIN_WIDTH = 900;
const NAV_MEDIUM_MIN_WIDTH = 680;

function getNavDensity(width: number): NavDensity {
    // width 0 = not measured yet (first paint); default to full to avoid a
    // collapsed flash before the ResizeObserver reports.
    if (width === 0 || width >= NAV_FULL_MIN_WIDTH) return 'full';
    if (width >= NAV_MEDIUM_MIN_WIDTH) return 'medium';
    return 'compact';
}

// Shape of an active execution as stored on the canvas
interface ActiveExecution {
    startedAt: number;
    nodeIds: Set<string>;
}

interface CanvasTopBarProps {
    // Workflow identity
    workflowTitle?: string;
    workflowId?: string;
    isRealWorkflow: boolean;
    nodes: Node[];
    edges: Edge[];
    onTitleChange?: (newTitle: string) => void;
    onBack?: () => void;

    // Tab state
    activeTab: string;
    onTabChange: (tab: CanvasTab) => void;
    onConfigViewExpandedChange: (expanded: boolean) => void;
    onFlowHelperTabChange: (tab: HelperTabType) => void;
    resourceCount: number;

    // Layout / compaction. Density is derived internally from the bar's
    // measured width; only the mobile flag is an input.
    isMobile: boolean;

    // Collaborators (desktop only)
    collaborators: Collaborator[];

    // File import + hidden input
    fileInputRef: React.RefObject<HTMLInputElement | null>;
    onImportWorkflow: () => void;
    onFileChange: (event: React.ChangeEvent<HTMLInputElement>) => void;
    onExportWorkflow: () => void;
    onAutolayout: () => void;
    onDeleteWorkflow: () => void;

    // Dialog openers
    onShareDialogOpen: () => void;
    onSettingsDialogOpen: () => void;

    // Checkpoint restore
    onCheckpointRestore: (nodes: Node[], edges: Edge[]) => void;

    // Run / Stop
    isWorkflowRunning: boolean;
    activeExecutions: Map<string, ActiveExecution>;
    onRun: () => void;
    onStop: (executionId?: string) => void;
    onHoveredExecutionChange: (id: string | null) => void;
}

// The top-of-canvas navbar with tab buttons on the left, workflow title in the
// middle (via AppNavbar), and action buttons on the right. Extracted from
// FlowCanvas to keep the main render focused on the canvas itself.
export function CanvasTopBar(props: CanvasTopBarProps) {
    const {
        workflowTitle,
        workflowId,
        isRealWorkflow,
        nodes,
        edges,
        onTitleChange,
        onBack,
        activeTab,
        onTabChange,
        onConfigViewExpandedChange,
        onFlowHelperTabChange,
        resourceCount,
        isMobile,
        collaborators,
        fileInputRef,
        onImportWorkflow,
        onFileChange,
        onExportWorkflow,
        onAutolayout,
        onDeleteWorkflow,
        onShareDialogOpen,
        onSettingsDialogOpen,
        onCheckpointRestore,
        isWorkflowRunning,
        activeExecutions,
        onRun,
        onStop,
        onHoveredExecutionChange,
    } = props;

    // Measure the bar's own width (not the viewport) to drive compaction.
    const [navRef, navWidth] = useElementWidth<HTMLDivElement>();
    const density: NavDensity = isMobile ? 'full' : getNavDensity(navWidth);
    // Chrome (padding, title width, divider) tightens as soon as we leave the
    // roomy stage; right-side actions only iconify at the tightest stage.
    const barCompact = isMobile || density !== 'full';
    const actionsCompact = density === 'compact';

    return (
        <AppNavbar
            title={workflowTitle}
            onTitleChange={onTitleChange}
            onBack={onBack}
            compact={barCompact}
            rootRef={navRef}
            leftContent={
                <NavbarTabs
                    activeTab={activeTab}
                    onTabChange={onTabChange}
                    onConfigViewExpandedChange={onConfigViewExpandedChange}
                    onFlowHelperTabChange={onFlowHelperTabChange}
                    resourceCount={resourceCount}
                    density={density}
                    isMobile={isMobile}
                    workflowId={workflowId}
                    nodes={nodes}
                    edges={edges}
                    onCheckpointRestore={onCheckpointRestore}
                />
            }
            rightContent={
                <NavbarActions
                    workflowId={workflowId}
                    isRealWorkflow={isRealWorkflow}
                    nodes={nodes}
                    activeTab={activeTab}
                    isCompact={actionsCompact}
                    isMobile={isMobile}
                    collaborators={collaborators}
                    fileInputRef={fileInputRef}
                    onImportWorkflow={onImportWorkflow}
                    onFileChange={onFileChange}
                    onExportWorkflow={onExportWorkflow}
                    onAutolayout={onAutolayout}
                    onDeleteWorkflow={onDeleteWorkflow}
                    onShareDialogOpen={onShareDialogOpen}
                    onSettingsDialogOpen={onSettingsDialogOpen}
                    isWorkflowRunning={isWorkflowRunning}
                    activeExecutions={activeExecutions}
                    onRun={onRun}
                    onStop={onStop}
                    onHoveredExecutionChange={onHoveredExecutionChange}
                />
            }
        />
    );
}

// ─── Left: Tab buttons ────────────────────────────────────────────────────────

interface NavbarTabsProps
    extends Pick<
        CanvasTopBarProps,
        'activeTab' | 'onTabChange' | 'onConfigViewExpandedChange' | 'onFlowHelperTabChange' |
        'resourceCount' | 'isMobile' | 'workflowId' |
        'nodes' | 'edges' | 'onCheckpointRestore'
    > {
    density: NavDensity;
}

function NavbarTabs({
    activeTab,
    onTabChange,
    onConfigViewExpandedChange,
    onFlowHelperTabChange,
    resourceCount,
    density,
    isMobile,
    workflowId,
    nodes,
    edges,
    onCheckpointRestore,
}: NavbarTabsProps) {
    // Primary tabs keep their labels until the tightest stage; secondary tabs
    // shed labels one stage earlier. (Mobile shows labels regardless — only
    // Interface/Workflow render there, gated below.)
    const primaryCompact = density === 'compact';
    const secondaryCompact = density !== 'full';
    return (
        <TooltipProvider delayDuration={200}>
            <div className="relative flex items-center gap-1">
                <NavbarTab
                    tab="interface"
                    label="Interface"
                    icon={LayoutGrid}
                    activeTab={activeTab}
                    compact={primaryCompact}
                    isMobile={isMobile}
                    tooltip="Interface — forms, dashboards, UI"
                    shortcut="I"
                    tourTarget="interface-tab"
                    onClick={() => {
                        onTabChange('interface');
                        // Pre-select the Nodes sub-tab (which now hosts the
                        // interface blocks) so it's ready when the user manually
                        // opens FlowHelperView, but don't auto-expand —
                        // FlowHelperView should only open via a node click or an
                        // explicit user gesture.
                        onFlowHelperTabChange('home');
                    }}
                />
                <NavbarTab
                    tab="canvas"
                    label="Workflow"
                    icon={Grid}
                    activeTab={activeTab}
                    compact={primaryCompact}
                    isMobile={isMobile}
                    tooltip="Workflow — backend and automations"
                    shortcut="W"
                    onClick={() => onTabChange('canvas')}
                />
                {/* Logs + checkpoint + resources + setup — hidden on mobile */}
                {!isMobile && (
                    <>
                        <NavbarTab
                            tab="logs"
                            label="Logs"
                            icon={ClipboardList}
                            activeTab={activeTab}
                            compact={secondaryCompact}
                            isMobile={false}
                            tooltip="Execution logs and history"
                            shortcut="L"
                            onClick={() => onTabChange('logs')}
                        />
                        <WorkflowCheckpointControl
                            workflowId={workflowId}
                            nodes={nodes}
                            edges={edges}
                            onRestore={onCheckpointRestore}
                            compact={secondaryCompact}
                        />
                        {(resourceCount > 0 || activeTab === 'resources') && (
                            <NavbarTab
                                tab="resources"
                                label="Resources"
                                icon={FolderOpen}
                                activeTab={activeTab}
                                compact={secondaryCompact}
                                isMobile={false}
                                tooltip="Uploaded files and resources"
                                onClick={() => onTabChange('resources')}
                            />
                        )}
                        <NavbarTab
                            tab="setup"
                            label="Setup"
                            icon={ListChecks}
                            activeTab={activeTab}
                            compact={secondaryCompact}
                            isMobile={false}
                            tooltip="Setup — what this workflow still needs"
                            shortcut="S"
                            onClick={() => onTabChange('setup')}
                        />
                    </>
                )}
            </div>
        </TooltipProvider>
    );
}

interface NavbarTabProps {
    tab: CanvasTab;
    label: string;
    icon: LucideIcon;
    activeTab: string;
    compact: boolean;
    isMobile: boolean;
    tooltip: string;
    /** Single-key shortcut shown in the tooltip (e.g. 'W'). */
    shortcut?: string;
    /** Optional data-tour-target for anchoring a GuidedTourHighlight step. */
    tourTarget?: string;
    onClick: () => void;
}

const NAVBAR_TOOLTIP_CLASS =
    'rounded-lg border border-border dark:border-white/10 bg-background dark:bg-[#0a0a0b] px-3 py-1.5 text-xs font-medium tracking-tight text-foreground shadow-2xl dark:shadow-black/60 backdrop-blur-md';

function NavbarTab({ tab, label, icon: Icon, activeTab, compact, isMobile, tooltip, shortcut, tourTarget, onClick }: NavbarTabProps) {
    const isActive = activeTab === tab;
    return (
        <Tooltip>
            <TooltipTrigger asChild>
                <button
                    onClick={onClick}
                    data-tour-target={tourTarget}
                    className={`relative ${compact ? 'px-2' : 'px-4'} py-1.5 text-xs font-semibold transition-all duration-200 flex items-center justify-center gap-2 rounded-md ${
                        isActive ? 'text-foreground bg-foreground/10 shadow-sm' : 'text-muted-foreground hover:text-foreground hover:bg-foreground/5'
                    }`}
                    aria-label={label}
                >
                    <Icon className={`h-4 w-4 ${isActive ? 'opacity-90' : 'opacity-70'}`} />
                    {(!compact || isMobile) && label}
                </button>
            </TooltipTrigger>
            <TooltipContent side="bottom" sideOffset={16} className={NAVBAR_TOOLTIP_CLASS}>
                <span className="flex items-center gap-2">
                    {tooltip}
                    {shortcut && <KeyHint keys={[shortcut]} />}
                </span>
            </TooltipContent>
        </Tooltip>
    );
}

// ─── Right: Action buttons ────────────────────────────────────────────────────

interface NavbarActionsProps
    extends Pick<
        CanvasTopBarProps,
        'workflowId' | 'isRealWorkflow' | 'nodes' | 'activeTab' | 'isMobile' |
        'collaborators' | 'fileInputRef' | 'onImportWorkflow' | 'onFileChange' |
        'onExportWorkflow' | 'onAutolayout' | 'onDeleteWorkflow' | 'onShareDialogOpen' |
        'onSettingsDialogOpen' | 'isWorkflowRunning' | 'activeExecutions' | 'onRun' |
        'onStop' | 'onHoveredExecutionChange'
    > {
    /** Icon-only actions at the tightest stage. */
    isCompact: boolean;
}

function NavbarActions({
    workflowId,
    isRealWorkflow,
    nodes,
    activeTab,
    isCompact,
    isMobile,
    collaborators,
    fileInputRef,
    onImportWorkflow,
    onFileChange,
    onExportWorkflow,
    onAutolayout,
    onDeleteWorkflow,
    onShareDialogOpen,
    onSettingsDialogOpen,
    isWorkflowRunning,
    activeExecutions,
    onRun,
    onStop,
    onHoveredExecutionChange,
}: NavbarActionsProps) {
    const showMultiStopDropdown = !isMobile && activeExecutions.size > 1;
    const showRunStopToggle = !isMobile && !showMultiStopDropdown;

    return (
        <>
            {!isMobile && <CollaboratorAvatars collaborators={collaborators} />}

            {/* Hidden file input for workflow import — wired to the dropdown's Import item */}
            <input
                ref={fileInputRef}
                type="file"
                accept=".json"
                onChange={onFileChange}
                style={{ display: 'none' }}
                aria-label="Import workflow file"
            />

            {!isMobile && (
                <TooltipProvider delayDuration={200}>
                    <Tooltip>
                        <TooltipTrigger asChild>
                            <Button
                                variant="ghost"
                                size="sm"
                                onClick={onShareDialogOpen}
                                className="h-9 w-9 p-0 text-muted-foreground hover:text-foreground hover:bg-accent dark:hover:bg-zinc-800/50 rounded-full"
                                aria-label="Share workflow"
                            >
                                <Share2 className="h-4 w-4" />
                            </Button>
                        </TooltipTrigger>
                        <TooltipContent side="bottom" sideOffset={16} className={NAVBAR_TOOLTIP_CLASS}>
                            Share workflow
                        </TooltipContent>
                    </Tooltip>
                    <MoreMenu
                        workflowId={workflowId}
                        isRealWorkflow={isRealWorkflow}
                        onImportWorkflow={onImportWorkflow}
                        onExportWorkflow={onExportWorkflow}
                        onAutolayout={onAutolayout}
                        onSettingsDialogOpen={onSettingsDialogOpen}
                        onDeleteWorkflow={onDeleteWorkflow}
                    />
                </TooltipProvider>
            )}

            {showMultiStopDropdown && (
                <MultiStopDropdown
                    isCompact={isCompact}
                    activeExecutions={activeExecutions}
                    onStop={onStop}
                    onHoveredExecutionChange={onHoveredExecutionChange}
                />
            )}

            {showRunStopToggle && (
                <RunStopButton
                    isCompact={isCompact}
                    isWorkflowRunning={isWorkflowRunning}
                    onRun={onRun}
                    onStop={() => onStop()}
                />
            )}
        </>
    );
}

// ─── Sub-components for the right-side actions ────────────────────────────────

interface MoreMenuProps {
    workflowId?: string;
    isRealWorkflow: boolean;
    onImportWorkflow: () => void;
    onExportWorkflow: () => void;
    onAutolayout: () => void;
    onSettingsDialogOpen: () => void;
    onDeleteWorkflow: () => void;
}

function MoreMenu({
    workflowId,
    isRealWorkflow,
    onImportWorkflow,
    onExportWorkflow,
    onAutolayout,
    onSettingsDialogOpen,
    onDeleteWorkflow,
}: MoreMenuProps) {
    const itemClass = cn(
        'flex items-center gap-3 px-2.5 py-2 rounded-md cursor-pointer',
        'text-muted-foreground dark:text-white/50 hover:text-foreground hover:bg-foreground/[0.04]',
        'transition-colors duration-100',
        'focus:bg-foreground/[0.06] focus:text-foreground'
    );
    const iconDotClass = 'w-6 h-6 rounded-full bg-foreground/5 flex items-center justify-center';

    return (
        <DropdownMenu>
            <Tooltip>
                <TooltipTrigger asChild>
                    {/* inline-flex wrapper gives each asChild trigger its own
                        element: Tooltip composes onto the span, Dropdown onto the
                        Button. Two Popper-anchor state-setter refs on one element
                        through a nested Slot chain churns the composed-ref identity
                        every commit → detach/re-attach → setState loop → React #185
                        (radix #3799). The span shrink-wraps the 36×36 button so the
                        tooltip still anchors over it. */}
                    <span className="inline-flex">
                        <DropdownMenuTrigger asChild>
                            <Button
                                variant="ghost"
                                size="sm"
                                className="h-9 w-9 p-0 text-muted-foreground hover:text-foreground hover:bg-accent dark:hover:bg-zinc-800/50 rounded-full"
                                aria-label="More options"
                            >
                                <MoreVertical className="h-4 w-4" />
                            </Button>
                        </DropdownMenuTrigger>
                    </span>
                </TooltipTrigger>
                <TooltipContent side="bottom" sideOffset={16} className={NAVBAR_TOOLTIP_CLASS}>
                    More options
                </TooltipContent>
            </Tooltip>
            <DropdownMenuContent
                align="end"
                sideOffset={8}
                className={cn(
                    'min-w-[200px] p-1.5',
                    'bg-popover/95 dark:bg-zinc-900/98 backdrop-blur-xl',
                    'border border-border dark:border-white/10',
                    'shadow-xl dark:shadow-black/40',
                    'rounded-lg'
                )}
            >
                <DropdownMenuItem onClick={onImportWorkflow} className={itemClass}>
                    <div className={iconDotClass}>
                        <Upload className="w-3.5 h-3.5" />
                    </div>
                    <span className="text-sm">Import workflow</span>
                </DropdownMenuItem>
                <DropdownMenuItem onClick={onExportWorkflow} className={itemClass}>
                    <div className={iconDotClass}>
                        <Download className="w-3.5 h-3.5" />
                    </div>
                    <span className="text-sm">Export workflow</span>
                </DropdownMenuItem>
                <DropdownMenuItem onClick={onAutolayout} className={itemClass}>
                    <div className={iconDotClass}>
                        <Paintbrush className="w-3.5 h-3.5" />
                    </div>
                    <span className="text-sm">Auto-layout</span>
                </DropdownMenuItem>
                <DropdownMenuSeparator className="my-1.5 bg-foreground/[0.06]" />
                <DropdownMenuItem onClick={onSettingsDialogOpen} className={itemClass}>
                    <div className={iconDotClass}>
                        <Settings className="w-3.5 h-3.5" />
                    </div>
                    <span className="text-sm">Settings</span>
                </DropdownMenuItem>
                {workflowId && isRealWorkflow && (
                    <>
                        <DropdownMenuSeparator className="my-1.5 bg-foreground/[0.06]" />
                        <DropdownMenuItem
                            onClick={onDeleteWorkflow}
                            className={cn(
                                'flex items-center gap-3 px-2.5 py-2 rounded-md cursor-pointer',
                                'text-red-600/70 dark:text-red-400/70 hover:text-red-600 dark:hover:text-red-400 hover:bg-red-500/[0.06]',
                                'transition-colors duration-100',
                                'focus:bg-red-500/[0.08] focus:text-red-600 dark:focus:text-red-400'
                            )}
                        >
                            <div className="w-6 h-6 rounded-full bg-red-500/10 flex items-center justify-center">
                                <Trash2 className="w-3.5 h-3.5" />
                            </div>
                            <span className="text-sm">Delete workflow</span>
                        </DropdownMenuItem>
                    </>
                )}
            </DropdownMenuContent>
        </DropdownMenu>
    );
}

const GRADIENT_ANIMATION_STYLE = {
    background:
        'linear-gradient(90deg, hsl(var(--secondary)) 0%, hsl(var(--accent)) 35%, hsl(var(--muted-foreground) / 0.45) 50%, hsl(var(--accent)) 65%, hsl(var(--secondary)) 100%)',
    backgroundSize: '300% 100%',
    animation: 'gradient-move 2s linear infinite',
} as const;

interface MultiStopDropdownProps {
    isCompact: boolean;
    activeExecutions: Map<string, ActiveExecution>;
    onStop: (executionId?: string) => void;
    onHoveredExecutionChange: (id: string | null) => void;
}

function MultiStopDropdown({
    isCompact,
    activeExecutions,
    onStop,
    onHoveredExecutionChange,
}: MultiStopDropdownProps) {
    return (
        <DropdownMenu onOpenChange={(open) => { if (!open) onHoveredExecutionChange(null); }}>
            <DropdownMenuTrigger asChild>
                <Button
                    size="sm"
                    className={`h-9 ${isCompact ? 'w-9 px-0 rounded-full' : 'px-4'} text-sm font-medium relative overflow-hidden bg-secondary text-secondary-foreground border-border dark:border-zinc-700 hover:bg-red-900/50 hover:border-red-700`}
                    aria-label="Stop executions"
                    title="Stop"
                >
                    <div className="absolute inset-0" style={GRADIENT_ANIMATION_STYLE} />
                    <span className="relative flex items-center gap-1.5">
                        <X className="h-3 w-3" />
                        {!isCompact && (
                            <>
                                Stop ({activeExecutions.size})
                                <ChevronDown className="h-3 w-3 ml-0.5" />
                            </>
                        )}
                    </span>
                </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent
                align="end"
                sideOffset={8}
                className={cn(
                    'min-w-[180px] p-1.5',
                    'bg-popover/95 dark:bg-zinc-900/98 backdrop-blur-xl',
                    'border border-border dark:border-white/10',
                    'shadow-xl dark:shadow-black/40',
                    'rounded-lg'
                )}
            >
                {[...activeExecutions.entries()]
                    .filter(([id]) => !id.startsWith('pending-'))
                    .map(([id], i) => (
                        <DropdownMenuItem
                            key={id}
                            onClick={() => onStop(id)}
                            onMouseEnter={() => onHoveredExecutionChange(id)}
                            className={cn(
                                'flex items-center gap-3 px-2.5 py-2 rounded-md cursor-pointer group',
                                'text-muted-foreground dark:text-white/50 hover:text-foreground hover:bg-foreground/[0.04]',
                                'transition-colors duration-100',
                                'focus:bg-foreground/[0.06] focus:text-foreground'
                            )}
                        >
                            <div className="w-5 h-5 flex items-center justify-center relative">
                                {/* Pulsing ring — default; hidden on hover */}
                                <span
                                    className="absolute inset-0 rounded-full border-2 border-orange-400/50 animate-ping group-hover:hidden"
                                    style={{ animationDuration: '1.5s' }}
                                />
                                <span className="w-2.5 h-2.5 rounded-full bg-orange-400 group-hover:hidden" />
                                {/* X icon — hidden; shown on hover */}
                                <X className="h-3 w-3 text-red-600 dark:text-red-400 hidden group-hover:block" />
                            </div>
                            <span className="text-sm">Run #{i + 1}</span>
                            <span className="text-xs text-foreground/20 ml-auto font-mono">{id.slice(0, 6)}</span>
                        </DropdownMenuItem>
                    ))}
                <DropdownMenuSeparator className="my-1.5 bg-foreground/[0.06]" />
                <DropdownMenuItem
                    onClick={() => onStop()}
                    className={cn(
                        'flex items-center gap-3 px-2.5 py-2 rounded-md cursor-pointer',
                        'text-red-600 dark:text-red-400 hover:text-red-700 dark:hover:text-red-300 hover:bg-red-500/[0.08]',
                        'transition-colors duration-100',
                        'focus:bg-red-500/[0.1] focus:text-red-700 dark:focus:text-red-300',
                        'font-medium'
                    )}
                >
                    <div className="w-5 h-5 rounded-full bg-red-500/10 flex items-center justify-center">
                        <X className="h-2.5 w-2.5" />
                    </div>
                    <span className="text-sm">Stop all</span>
                </DropdownMenuItem>
            </DropdownMenuContent>
        </DropdownMenu>
    );
}

function RunStopButton({
    isCompact,
    isWorkflowRunning,
    onRun,
    onStop,
}: {
    isCompact: boolean;
    isWorkflowRunning: boolean;
    onRun: () => void;
    onStop: () => void;
}) {
    return (
        <TooltipProvider delayDuration={200}>
            <Tooltip>
                <TooltipTrigger asChild>
                    <Button
                        size="sm"
                        onClick={isWorkflowRunning ? onStop : onRun}
                        className={`h-9 ${isCompact ? 'w-9 px-0 rounded-full' : 'px-4'} text-sm font-medium relative overflow-hidden ${
                            isWorkflowRunning
                                ? 'bg-secondary text-secondary-foreground border-border dark:border-zinc-700 hover:bg-red-900/50 hover:border-red-700'
                                : 'bg-primary text-primary-foreground hover:bg-primary/90 border-transparent shadow-sm font-semibold'
                        }`}
                        aria-label={isWorkflowRunning ? 'Stop workflow' : 'Run workflow'}
                    >
                        {isWorkflowRunning && <div className="absolute inset-0" style={GRADIENT_ANIMATION_STYLE} />}
                        <span className="relative flex items-center gap-1.5">
                            {isWorkflowRunning ? <X className="h-3 w-3" /> : <Play className="h-3 w-3" />}
                            {!isCompact && (isWorkflowRunning ? 'Stop' : 'Run')}
                        </span>
                    </Button>
                </TooltipTrigger>
                <TooltipContent side="bottom" sideOffset={16} className={NAVBAR_TOOLTIP_CLASS}>
                    <span className="flex items-center gap-1.5">
                        {isWorkflowRunning ? 'Stop workflow' : 'Run workflow'}
                        <KeyHint keys={['Shift', 'R']} />
                    </span>
                </TooltipContent>
            </Tooltip>
        </TooltipProvider>
    );
}
