// Shared mouse-drag helper for the three resize interactions in FlowHelperView
// (horizontal input/output panel widths, collapsed split ratio, vertical height).
//
// Each caller captures its own "initial value" before calling beginResizeDrag,
// then uses the raw pixel delta in onMove (for direct DOM mutation during drag)
// and onCommit (to write final value to React state).

type ResizeConfig = {
    axis: 'x' | 'y';
    cursor: 'col-resize' | 'row-resize' | 'ns-resize';
    /** Apply intermediate value during drag — typically a DOM mutation, no re-render. */
    onMove: (delta: number) => void;
    /** Commit final value to React state. */
    onCommit: (delta: number) => void;
};

export function beginResizeDrag(event: React.MouseEvent, config: ResizeConfig): void {
    event.preventDefault();
    const startPos = config.axis === 'x' ? event.clientX : event.clientY;

    const currentDelta = (e: MouseEvent) =>
        (config.axis === 'x' ? e.clientX : e.clientY) - startPos;

    const handleMove = (e: MouseEvent) => config.onMove(currentDelta(e));
    const handleUp = (e: MouseEvent) => {
        config.onCommit(currentDelta(e));
        document.removeEventListener('mousemove', handleMove);
        document.removeEventListener('mouseup', handleUp);
        document.body.style.cursor = '';
        document.body.style.userSelect = '';
    };

    document.addEventListener('mousemove', handleMove);
    document.addEventListener('mouseup', handleUp);
    document.body.style.cursor = config.cursor;
    document.body.style.userSelect = 'none';
}
