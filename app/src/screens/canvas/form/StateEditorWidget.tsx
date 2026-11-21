// State Editor Widget - JSON editor using CodeMirror 6 for State Manager node.
// Supports drag-and-drop of references from Input panel.
// Replaces the previous Prism-based overlay pattern for better performance
// with large JSON (CodeMirror only highlights visible lines).

import { useState, useCallback, useRef, useEffect, memo } from 'react';
import { useDroppable } from '@dnd-kit/core';
import { EditorView, keymap, placeholder as cmPlaceholder } from '@codemirror/view';
import { EditorState } from '@codemirror/state';
import { json } from '@codemirror/lang-json';
import { oneDarkHighlightStyle } from '@codemirror/theme-one-dark';
import { syntaxHighlighting } from '@codemirror/language';

// CodeMirror theme matching the existing dark UI
const editorTheme = EditorView.theme({
    '&': {
        fontSize: '12px',
        backgroundColor: 'transparent',
        color: '#e6e6e6',
        maxHeight: '300px',
    },
    '.cm-scroller': {
        fontFamily: '"JetBrains Mono", "Fira Code", "SF Mono", Consolas, monospace',
        lineHeight: '18px',
        overflow: 'auto',
        minHeight: '120px',
        maxHeight: '300px',
    },
    '.cm-content': { padding: '8px' },
    '.cm-gutters': { display: 'none' },
    '.cm-activeLine': { backgroundColor: 'rgb(39 39 42 / 0.3)' },
    '.cm-cursor, .cm-dropCursor': { borderLeftColor: '#e4e4e7 !important' },
    '&.cm-focused': { outline: 'none' },
    '.cm-placeholder': {
        color: 'rgb(82 82 91)',
        fontStyle: 'normal',
    },
}, { dark: true });

interface StateEditorWidgetProps {
    fieldKey: string;
    placeholder?: string;
    value: Record<string, unknown>;
    onChange: (key: string, value: Record<string, unknown>) => void;
}

export const StateEditorWidget = memo(function StateEditorWidget({
    fieldKey,
    placeholder = '{\n  "counter": 0,\n  "items": []\n}',
    value,
    onChange,
}: StateEditorWidgetProps) {
    const [error, setError] = useState<string | null>(null);
    const [isFocused, setIsFocused] = useState(false);
    const editorContainerRef = useRef<HTMLDivElement>(null);
    const viewRef = useRef<EditorView | null>(null);
    const onChangeRef = useRef(onChange);
    onChangeRef.current = onChange;
    const fieldKeyRef = useRef(fieldKey);
    fieldKeyRef.current = fieldKey;
    const lastValueRef = useRef(value);
    const isFocusedRef = useRef(false);

    // Set up droppable
    const { setNodeRef, isOver, active } = useDroppable({
        id: `state-editor-${fieldKey}`,
        data: { type: 'state-editor-field', fieldKey },
    });

    const isJsonFieldDrag = active?.data?.current?.type === 'json-field-reference';

    // Initialize CodeMirror
    useEffect(() => {
        if (!editorContainerRef.current) return;

        const initialDoc = (() => {
            try { return JSON.stringify(value || {}, null, 2); }
            catch { return '{}'; }
        })();

        const view = new EditorView({
            state: EditorState.create({
                doc: initialDoc,
                extensions: [
                    json(),
                    syntaxHighlighting(oneDarkHighlightStyle),
                    editorTheme,
                    cmPlaceholder(placeholder),
                    keymap.of([{
                        key: 'Tab',
                        run: (v) => { v.dispatch(v.state.replaceSelection('  ')); return true; },
                    }]),
                    EditorView.updateListener.of((update) => {
                        if (update.docChanged) {
                            const text = update.state.doc.toString();
                            try {
                                const parsed = JSON.parse(text);
                                setError(null);
                                lastValueRef.current = parsed;
                                onChangeRef.current(fieldKeyRef.current, parsed);
                            } catch {
                                setError('Invalid JSON');
                            }
                        }
                        if (update.focusChanged) {
                            isFocusedRef.current = update.view.hasFocus;
                            setIsFocused(update.view.hasFocus);
                        }
                    }),
                    EditorView.lineWrapping,
                ],
            }),
            parent: editorContainerRef.current,
        });
        viewRef.current = view;
        return () => { view.destroy(); viewRef.current = null; };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    // Sync external value changes into editor (but not while editing)
    useEffect(() => {
        const view = viewRef.current;
        if (!view || isFocusedRef.current) return;
        try {
            const currentStr = JSON.stringify(lastValueRef.current);
            const newStr = JSON.stringify(value);
            if (currentStr !== newStr) {
                lastValueRef.current = value;
                const formatted = JSON.stringify(value || {}, null, 2);
                const cur = view.state.doc.toString();
                if (cur !== formatted) {
                    view.dispatch({ changes: { from: 0, to: cur.length, insert: formatted } });
                }
                setError(null);
            }
        } catch {
            // Keep current text if value is invalid
        }
    }, [value]);

    // Insert reference at cursor (for drag-and-drop from Input panel)
    const insertReference = useCallback((reference: string) => {
        const view = viewRef.current;
        if (!view) return;
        const pos = view.state.selection.main.head;
        view.dispatch({ changes: { from: pos, insert: reference } });
        view.focus();

        // Try to parse after insertion
        const newText = view.state.doc.toString();
        try {
            const parsed = JSON.parse(newText);
            setError(null);
            lastValueRef.current = parsed;
            onChange(fieldKey, parsed);
        } catch {
            setError('Invalid JSON');
        }
    }, [fieldKey, onChange]);

    // Expose insertReference on the DOM element for drop handling
    useEffect(() => {
        const el = editorContainerRef.current;
        if (el) {
            (el as any).__insertReference = insertReference;
            (el as any).__stateEditorFieldKey = fieldKey;
        }
    }, [insertReference, fieldKey]);

    // Format/prettify
    const handleFormat = useCallback(() => {
        const view = viewRef.current;
        if (!view) return;
        try {
            const parsed = JSON.parse(view.state.doc.toString());
            const formatted = JSON.stringify(parsed, null, 2);
            view.dispatch({ changes: { from: 0, to: view.state.doc.length, insert: formatted } });
            setError(null);
            lastValueRef.current = parsed;
            onChange(fieldKey, parsed);
        } catch {
            setError('Cannot format: Invalid JSON');
        }
    }, [fieldKey, onChange]);

    const showDropHint = isOver && isJsonFieldDrag;

    return (
        <div className="space-y-1.5">
            {/* Format button */}
            <div className="flex justify-end">
                <button
                    onClick={handleFormat}
                    className="text-[10px] text-muted-foreground dark:text-zinc-500 hover:text-foreground/80 transition-colors px-2 py-0.5 rounded hover:bg-foreground/[0.05]"
                >
                    Format JSON
                </button>
            </div>

            {/* Editor container with drop target */}
            <div
                ref={(node) => {
                    setNodeRef(node);
                    if (node) {
                        (node as any).__insertReference = insertReference;
                        (node as any).__stateEditorFieldKey = fieldKey;
                    }
                }}
                data-state-editor-field-key={fieldKey}
                className={`relative rounded-lg border bg-card/50 overflow-hidden transition-all ${
                    error
                        ? 'border-red-500/50'
                        : showDropHint
                        ? 'border-muted-foreground/60 dark:border-zinc-500/60 ring-2 ring-muted-foreground/20 dark:ring-zinc-500/20'
                        : isFocused
                        ? 'border-foreground/20'
                        : 'border-border dark:border-white/[0.08]'
                }`}
            >
                {/* CodeMirror editor */}
                <div ref={editorContainerRef} />

                {/* Drop hint overlay */}
                {showDropHint && (
                    <div className="absolute inset-0 flex items-center justify-center bg-card/95 rounded-lg pointer-events-none border-2 border-dashed border-muted-foreground/50 dark:border-zinc-500/50">
                        <span className="text-xs text-foreground/80 font-medium">Drop to insert reference</span>
                    </div>
                )}
            </div>

            {/* Error message */}
            {error && (
                <div className="text-[10px] text-red-600 dark:text-red-400 flex items-center gap-1">
                    <span>⚠</span> {error}
                </div>
            )}

            {/* Help text */}
            <div className="text-[10px] text-muted-foreground/70 dark:text-zinc-600">
                Define initial state values. Drag references from Input panel to include dynamic values.
            </div>
        </div>
    );
}, (prev, next) =>
    // Only re-render when fieldKey or value reference actually changes.
    // During drag, the parent re-renders with new object refs for the node,
    // but value points to the same state object (identity preserved).
    prev.fieldKey === next.fieldKey && prev.value === next.value
);
