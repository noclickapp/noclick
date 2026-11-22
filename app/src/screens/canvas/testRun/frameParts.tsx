// What a Test Run's and a run's frames draw with whoever renders them (the `canvas.frames` slot, declared with the
// canvas's others in ../slots.ts): a sent message's or a reply's text from its Markdown, and the mark of work under
// way. The frames are drawn outside the canvas too (a page that shows one finished run), so they read their slot
// through a handle of its own here (`FRAMES`: the slot's name and standard), and a page that shows a frame loads
// none of the canvas's other standards. The standards load nothing until they first draw, so a page that fills the
// slot (or shows a frame with neither) never downloads them.
import { lazy, Suspense, type ComponentType } from 'react';
import { useSlot, type Slot } from '@/slots';

export interface FrameMarkdownProps {
    content: string;
    className?: string;
    /** A single line break is a break, as in a chat message. */
    breaks?: boolean;
}

export interface FrameParts {
    /** A sent message's or a reply's text, drawn from its Markdown. */
    Markdown: ComponentType<FrameMarkdownProps>;
    /** Beside "Thinking", and while the screen reads the workflow: the mark of work under way, `size` pixels square. */
    Working: ComponentType<{ size: number }>;
}

const Doc = lazy(() => import('@/screens/resources/CodeView').then((m) => ({ default: m.MarkdownDoc })));

/** Markdown drawn as a README is; its plain text until that has loaded. */
function ReadmeMarkdown({ content, className, breaks }: FrameMarkdownProps) {
    // Two spaces before a newline is Markdown's own line break.
    const source = breaks ? content.replace(/([^\n])\n(?!\n)/g, '$1  \n') : content;
    return (
        <Suspense fallback={<div className={className}>{content}</div>}>
            <Doc source={source} className={className} />
        </Suspense>
    );
}

/** Work under way: a live dot. */
function WorkingDot({ size }: { size: number }) {
    return <span aria-hidden className="inline-block shrink-0 animate-pulse rounded-full bg-foreground/45" style={{ width: size, height: size }} />;
}

/** What stands in `canvas.frames` when no host fills it: Markdown drawn as a README is, a live dot for work under way. */
export const FRAME_STANDARD: FrameParts = { Markdown: ReadmeMarkdown, Working: WorkingDot };

/** The `canvas.frames` slot as the frames, and a host that fills it for a page outside the canvas, name it: the same
 *  place as ../slots.ts's FRAME_PARTS (slots are kept by name), without the canvas's other slots. */
export const FRAMES: Slot<FrameParts> = { name: 'canvas.frames', standard: FRAME_STANDARD };

/** A message's or a reply's text, from its Markdown. */
export function FrameMarkdown(props: FrameMarkdownProps) {
    const { Markdown } = useSlot(FRAMES);
    return <Markdown {...props} />;
}

/** The mark of work under way. */
export function WorkingMark({ size }: { size: number }) {
    const { Working } = useSlot(FRAMES);
    return <Working size={size} />;
}
