import { useCallback, useRef, useState } from 'react';
import { scaled } from '~/lib/constants';
import { beginResizeDrag } from './resize';

// Default + clamp constants for the input/output panels. Scaled by the
// active root-font-size tier so the limits track the rem-based UI.
const DEFAULT_PANEL_WIDTH = 260;
const MIN_PANEL_WIDTH = 200;
const CENTER_CONTENT_RESERVE = 280;

// Bundles the state, refs, and drag handlers for the three-column panel
// layout (input / middle content / output). When activeTab is null the
// panels share a collapsed split ratio; the consumer is responsible for
// the activeTab-aware style. Header-strip compaction is delegated to useFit.
export function usePanelLayout() {
    const [inputPanelWidth, setInputPanelWidth] = useState(() => scaled(DEFAULT_PANEL_WIDTH));
    const [outputPanelWidth, setOutputPanelWidth] = useState(() => scaled(DEFAULT_PANEL_WIDTH));
    // 0-1, where 0.5 = 50/50 split between input and output in collapsed mode
    const [collapsedSplitRatio, setCollapsedSplitRatio] = useState(0.5);

    // Manual search expansion override — clicking the collapsed search icon
    // expands the bar even when useFit has decided "search" should be compact.
    const [isSearchExpanded, setIsSearchExpanded] = useState(false);

    const headerRef = useRef<HTMLDivElement>(null);
    const inputPanelRef = useRef<HTMLDivElement>(null);
    const outputPanelRef = useRef<HTMLDivElement>(null);
    const contentAreaRef = useRef<HTMLDivElement>(null);

    // Horizontal panel resize: input grows right, output grows left.
    // Clamp so both panels keep at least MIN_PANEL_WIDTH and leave
    // CENTER_CONTENT_RESERVE for the middle content.
    const startResize = useCallback((e: React.MouseEvent, panel: 'input' | 'output') => {
        const minWidth = scaled(MIN_PANEL_WIDTH);
        const centerReserve = scaled(CENTER_CONTENT_RESERVE);
        const startWidth = panel === 'input' ? inputPanelWidth : outputPanelWidth;
        const clampPanelWidth = (rawWidth: number) => {
            const contentAreaWidth = contentAreaRef.current?.clientWidth || 1200;
            const otherPanelWidth = panel === 'input' ? outputPanelWidth : inputPanelWidth;
            const maxAllowed = Math.max(minWidth, contentAreaWidth - otherPanelWidth - centerReserve);
            return Math.max(minWidth, Math.min(maxAllowed, rawWidth));
        };
        const widthFor = (dx: number) => clampPanelWidth(startWidth + (panel === 'input' ? dx : -dx));
        const ref = panel === 'input' ? inputPanelRef : outputPanelRef;
        const setter = panel === 'input' ? setInputPanelWidth : setOutputPanelWidth;

        beginResizeDrag(e, {
            axis: 'x',
            cursor: 'col-resize',
            onMove: (dx) => {
                if (ref.current) ref.current.style.width = `${widthFor(dx)}px`;
            },
            onCommit: (dx) => setter(widthFor(dx)),
        });
    }, [inputPanelWidth, outputPanelWidth]);

    // Collapsed mode split: adjust the ratio between input and output panels,
    // clamped to 20%-80% so neither panel fully disappears.
    const startCollapsedResize = useCallback((e: React.MouseEvent) => {
        const containerWidth = contentAreaRef.current?.clientWidth || 0;
        if (containerWidth === 0) return;
        const startRatio = collapsedSplitRatio;
        const ratioFor = (dx: number) =>
            Math.max(0.2, Math.min(0.8, startRatio + dx / containerWidth));

        beginResizeDrag(e, {
            axis: 'x',
            cursor: 'col-resize',
            onMove: (dx) => {
                const r = ratioFor(dx);
                if (inputPanelRef.current) inputPanelRef.current.style.flex = `${r}`;
                if (outputPanelRef.current) outputPanelRef.current.style.flex = `${1 - r}`;
            },
            onCommit: (dx) => setCollapsedSplitRatio(ratioFor(dx)),
        });
    }, [collapsedSplitRatio]);

    return {
        // State
        inputPanelWidth,
        outputPanelWidth,
        collapsedSplitRatio,
        isSearchExpanded,
        setIsSearchExpanded,
        // Refs
        headerRef,
        inputPanelRef,
        outputPanelRef,
        contentAreaRef,
        // Drag handlers
        startResize,
        startCollapsedResize,
    };
}
