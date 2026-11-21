// What stands in the canvas's slots (slots.ts) when no host fills them: each works over the platform API alone, or
// says where on NoClick the thing is done and opens it there, never a gap.
import { lazy, Suspense, useContext, type ReactNode } from 'react';
import { ArrowUpRight, LayoutGrid, MessageCircle, Share2 } from 'lucide-react';
import { ConsoleContext } from '@/screens/console/hooks/useConsole';
import { NOCLICK_SITE, workflowUrl } from '@/screens/console/lib/site';
import { BUTTON_GHOST, BUTTON_PRIMARY, BUTTON_SECONDARY } from '@/ui/buttons';
import { DIALOG_MARK, ShellDialog } from '@/ui/ShellDialog';
import { cn } from '@/ui/utils';
import type { Presence } from './presence';
import type { CanvasBlockProps, CanvasBuilderProps, CanvasInterfaceProps, CanvasPresence, CanvasShareProps } from './slots';

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
