// Shared CodeMirror 6 editor hook and UI components used by both the JavaScript and Python
// function editors in the serverless function node. Centralizes theme, fullscreen, sidebar
// tracking, and editor lifecycle management.

import { useState, useRef, useEffect, useCallback, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { EditorView, keymap, placeholder as cmPlaceholder, lineNumbers } from '@codemirror/view';
import { EditorState, Compartment, type Extension } from '@codemirror/state';
import { oneDarkHighlightStyle } from '@codemirror/theme-one-dark';
import { syntaxHighlighting, defaultHighlightStyle } from '@codemirror/language';
import { useIsDark } from '~/hooks/useIsDark';

// ---------------------------------------------------------------------------
// Theme
// ---------------------------------------------------------------------------

// Editor body colors per theme. Light = white surface, near-black text, light
// syntax (defaultHighlightStyle); dark = the original zinc-900 one-dark look.
const EDITOR_PALETTE = {
    light: {
        bg: '#ffffff', text: '#1e1e21',
        gutterBg: 'rgb(250 250 250 / 0.8)', gutterText: 'rgb(161 161 170)',
        activeLine: 'rgb(0 0 0 / 0.035)', cursor: '#1e1e21', placeholder: 'rgb(161 161 170)',
    },
    dark: {
        bg: '#18181b', text: '#e4e4e7',
        gutterBg: 'rgb(24 24 27 / 0.8)', gutterText: 'rgb(82 82 91)',
        activeLine: 'rgb(39 39 42 / 0.3)', cursor: '#e4e4e7', placeholder: 'rgb(82 82 91)',
    },
};

function buildEditorTheme(isDark: boolean, fullscreen: boolean) {
    const c = isDark ? EDITOR_PALETTE.dark : EDITOR_PALETTE.light;
    return EditorView.theme({
        '&': {
            fontSize: '12px',
            backgroundColor: c.bg,
            color: c.text,
            ...(fullscreen ? { height: '100%' } : { maxHeight: '400px' }),
        },
        '.cm-scroller': {
            fontFamily: '"JetBrains Mono", "Fira Code", "SF Mono", Consolas, monospace',
            lineHeight: '18px',
            overflow: 'auto',
        },
        '.cm-content': { padding: '8px 0' },
        '.cm-gutters': {
            backgroundColor: c.gutterBg,
            borderRight: 'none',
            color: c.gutterText,
            fontSize: '10px',
            minWidth: '28px',
        },
        '.cm-lineNumbers .cm-gutterElement': { padding: '0 4px 0 0' },
        '.cm-activeLine': { backgroundColor: c.activeLine },
        '.cm-activeLineGutter': { backgroundColor: c.activeLine },
        '.cm-cursor, .cm-dropCursor': { borderLeftColor: `${c.cursor} !important` },
        '&.cm-focused': { outline: 'none' },
        '.cm-node-id-highlight': {
            backgroundColor: 'rgba(59, 130, 246, 0.25)',
            borderBottom: '2px solid rgba(96, 165, 250, 0.7)',
            borderRadius: '3px',
            padding: '1px 2px',
        },
        '.cm-placeholder': {
            color: c.placeholder,
            display: 'inline',
            height: '0',
            overflow: 'visible',
            verticalAlign: 'top',
            pointerEvents: 'none',
        },
    }, { dark: isDark });
}

// Theme + syntax highlight live in a Compartment so an app-theme toggle can
// reconfigure the running editor (light ⇆ dark) without recreating it.
const editorThemeCompartment = new Compartment();

function buildThemeExtension(isDark: boolean, fullscreen: boolean): Extension {
    return [
        buildEditorTheme(isDark, fullscreen),
        syntaxHighlighting(isDark ? oneDarkHighlightStyle : defaultHighlightStyle),
    ];
}

// ---------------------------------------------------------------------------
// Extensions builder
// ---------------------------------------------------------------------------

export function buildExtensions(
    isDark: boolean,
    fullscreen: boolean,
    langExtension: Extension,
    placeholderText: string,
    tabIndent: string,
    onChangeRef: React.RefObject<(v: string) => void>,
    extraExtensions?: Extension[],
): Extension[] {
    return [
        lineNumbers(),
        langExtension,
        editorThemeCompartment.of(buildThemeExtension(isDark, fullscreen)),
        cmPlaceholder(placeholderText),
        keymap.of([{
            key: 'Tab',
            run: (view) => {
                view.dispatch(view.state.replaceSelection(tabIndent));
                return true;
            },
        }]),
        EditorView.updateListener.of((update) => {
            if (update.docChanged) {
                onChangeRef.current(update.state.doc.toString());
            }
        }),
        EditorView.lineWrapping,
        ...(extraExtensions || []),
    ];
}

// ---------------------------------------------------------------------------
// Sidebar helpers
// ---------------------------------------------------------------------------

function getSidebarElement(): Element | null {
    return (
        document.querySelector('[data-tour-target="sidebar-expanded"]') ||
        document.querySelector('[data-tour-target="sidebar-collapsed"]')
    );
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

interface UseCodeMirrorEditorOptions {
    value: string;
    onChange: (value: string) => void;
    langExtension: Extension;
    placeholderText: string;
    tabIndent: string;
    extraExtensions?: Extension[];
}

export function useCodeMirrorEditor({ value, onChange, langExtension, placeholderText, tabIndent, extraExtensions }: UseCodeMirrorEditorOptions) {
    const [isFullscreen, setIsFullscreen] = useState(false);
    const [sidebarWidth, setSidebarWidth] = useState(50);

    const inlineEditorRef = useRef<HTMLDivElement>(null);
    const fullscreenEditorRef = useRef<HTMLDivElement>(null);
    const inlineViewRef = useRef<EditorView | null>(null);
    const fullscreenViewRef = useRef<EditorView | null>(null);
    const onChangeRef = useRef(onChange);
    onChangeRef.current = onChange;
    // Follows the app theme; the init effects read the latest via a ref (they
    // don't re-run on theme change — the reconfigure effects below handle that).
    const isDark = useIsDark();
    const isDarkRef = useRef(isDark);
    isDarkRef.current = isDark;

    // Initialize inline CodeMirror
    useEffect(() => {
        if (!inlineEditorRef.current) return;
        const view = new EditorView({
            state: EditorState.create({
                doc: value,
                extensions: buildExtensions(isDarkRef.current, false, langExtension, placeholderText, tabIndent, onChangeRef, extraExtensions),
            }),
            parent: inlineEditorRef.current,
        });
        inlineViewRef.current = view;
        return () => { view.destroy(); inlineViewRef.current = null; };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    // Reconfigure the live theme (light ⇆ dark) when the app theme flips.
    useEffect(() => {
        inlineViewRef.current?.dispatch({ effects: editorThemeCompartment.reconfigure(buildThemeExtension(isDark, false)) });
        if (isFullscreen) {
            fullscreenViewRef.current?.dispatch({ effects: editorThemeCompartment.reconfigure(buildThemeExtension(isDark, true)) });
        }
    }, [isDark, isFullscreen]);

    // Initialize fullscreen CodeMirror when entering fullscreen
    useEffect(() => {
        if (!isFullscreen || !fullscreenEditorRef.current) return;
        const view = new EditorView({
            state: EditorState.create({
                doc: value,
                extensions: buildExtensions(isDarkRef.current, true, langExtension, placeholderText, tabIndent, onChangeRef, extraExtensions),
            }),
            parent: fullscreenEditorRef.current,
        });
        fullscreenViewRef.current = view;
        view.focus();
        return () => { view.destroy(); fullscreenViewRef.current = null; };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [isFullscreen]);

    // Sync external value into the inline editor
    useEffect(() => {
        const view = inlineViewRef.current;
        if (!view) return;
        const cur = view.state.doc.toString();
        if (cur !== value) view.dispatch({ changes: { from: 0, to: cur.length, insert: value } });
    }, [value]);

    // Sync external value into the fullscreen editor
    useEffect(() => {
        if (!isFullscreen) return;
        const view = fullscreenViewRef.current;
        if (!view) return;
        const cur = view.state.doc.toString();
        if (cur !== value) view.dispatch({ changes: { from: 0, to: cur.length, insert: value } });
    }, [value, isFullscreen]);

    const handleCloseFullscreen = useCallback(() => {
        setIsFullscreen(false);
        requestAnimationFrame(() => {
            const view = inlineViewRef.current;
            if (!view) return;
            const cur = view.state.doc.toString();
            if (cur !== value) view.dispatch({ changes: { from: 0, to: cur.length, insert: value } });
        });
    }, [value]);

    const handleOpenFullscreen = useCallback(() => {
        const el = getSidebarElement();
        setSidebarWidth(el ? el.getBoundingClientRect().width : 50);
        setIsFullscreen(true);
    }, []);

    // Track sidebar resize/collapse while fullscreen is open
    useEffect(() => {
        if (!isFullscreen) return;
        const el = getSidebarElement();
        if (!el) return;
        const resizeObs = new ResizeObserver((entries) => {
            for (const entry of entries) setSidebarWidth(entry.contentRect.width);
        });
        resizeObs.observe(el);

        const mutationObs = new MutationObserver(() => {
            const current = getSidebarElement();
            if (current && current !== el) {
                setSidebarWidth(current.getBoundingClientRect().width);
                resizeObs.disconnect();
                resizeObs.observe(current);
            }
        });
        mutationObs.observe(document.body, {
            childList: true, subtree: true, attributes: true, attributeFilter: ['data-tour-target'],
        });

        return () => { resizeObs.disconnect(); mutationObs.disconnect(); };
    }, [isFullscreen]);

    // Escape key closes fullscreen
    useEffect(() => {
        if (!isFullscreen) return;
        const handleKey = (e: KeyboardEvent) => { if (e.key === 'Escape') handleCloseFullscreen(); };
        document.addEventListener('keydown', handleKey);
        return () => document.removeEventListener('keydown', handleKey);
    }, [isFullscreen, handleCloseFullscreen]);

    return {
        inlineEditorRef,
        fullscreenEditorRef,
        isFullscreen,
        sidebarWidth,
        handleOpenFullscreen,
        handleCloseFullscreen,
        lineCount: (value || '').split('\n').length,
    };
}

// ---------------------------------------------------------------------------
// Shared UI components
// ---------------------------------------------------------------------------

const ExpandIcon = () => (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <polyline points="15 3 21 3 21 9" />
        <polyline points="9 21 3 21 3 15" />
        <line x1="21" y1="3" x2="14" y2="10" />
        <line x1="3" y1="21" x2="10" y2="14" />
    </svg>
);

const CollapseIcon = () => (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <polyline points="4 14 10 14 10 20" />
        <polyline points="20 10 14 10 14 4" />
        <line x1="14" y1="10" x2="21" y2="3" />
        <line x1="3" y1="21" x2="10" y2="14" />
    </svg>
);

interface EditorHeaderProps {
    children: ReactNode;
    isFullscreen: boolean;
    onExpand: () => void;
    onCollapse: () => void;
}

export function EditorHeader({ children, isFullscreen, onExpand, onCollapse }: EditorHeaderProps) {
    return (
        <div className="flex items-center justify-between bg-muted/70 border-b border-border/50 dark:border-zinc-700/50 pl-3 pr-1.5 py-1.5 font-mono text-[12px] leading-[18px]">
            <div>{children}</div>
            <button
                type="button"
                onClick={isFullscreen ? onCollapse : onExpand}
                className="text-muted-foreground dark:text-zinc-500 hover:text-foreground/80 transition-colors p-0.5"
                title={isFullscreen ? 'Exit fullscreen (Esc)' : 'Expand editor'}
            >
                {isFullscreen ? <CollapseIcon /> : <ExpandIcon />}
            </button>
        </div>
    );
}

interface EditorFooterProps {
    lineCount: number;
    returnHint: ReactNode;
}

export function EditorFooter({ lineCount, returnHint }: EditorFooterProps) {
    return (
        <div className="flex items-center justify-between px-2 py-0.5 bg-muted/50 border-t border-border/30 dark:border-zinc-700/30">
            <span className="text-[9px] text-muted-foreground/70 dark:text-zinc-600">{returnHint}</span>
            <span className="text-[9px] text-muted-foreground/70 dark:text-zinc-600">
                {lineCount} line{lineCount !== 1 ? 's' : ''}
            </span>
        </div>
    );
}

interface EditorShellProps {
    inlineEditorRef: React.RefObject<HTMLDivElement | null>;
    fullscreenEditorRef: React.RefObject<HTMLDivElement | null>;
    isFullscreen: boolean;
    sidebarWidth: number;
    onClose: () => void;
    header: ReactNode;
    footer: ReactNode;
}

export function EditorShell({
    inlineEditorRef, fullscreenEditorRef, isFullscreen, sidebarWidth, onClose, header, footer,
}: EditorShellProps) {
    return (
        <>
            <div className="relative rounded-md overflow-hidden border border-border/50 dark:border-zinc-700/50 bg-card/90">
                {header}
                <div ref={inlineEditorRef} className="scrollbar-subtle" />
                {footer}
            </div>

            {isFullscreen && createPortal(
                <div
                    className="fixed inset-0 z-[9999] bg-black/80 flex items-stretch justify-center"
                    style={{ left: sidebarWidth }}
                    onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
                >
                    <div className="w-full flex flex-col bg-card m-6 rounded-lg overflow-hidden border border-border/50 dark:border-zinc-700/50">
                        {header}
                        <div
                            ref={fullscreenEditorRef}
                            className="flex-1 min-h-0 scrollbar-subtle [&_.cm-editor]:!h-full [&_.cm-editor]:!max-h-none [&_.cm-scroller]:!overflow-auto"
                        />
                        {footer}
                    </div>
                </div>,
                document.body,
            )}
        </>
    );
}
