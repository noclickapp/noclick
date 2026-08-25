// JavaScript function body editor with syntax highlighting for the serverless function node.
// Uses CodeMirror 6 via shared useCodeMirrorEditor hook.

import { useMemo } from 'react';
import { javascript } from '@codemirror/lang-javascript';
import { html } from '@codemirror/lang-html';
import { useCodeMirrorEditor, EditorHeader, EditorFooter, EditorShell } from './useCodeMirrorEditor';
import { nodeIdHighlighter } from './cm-node-id-highlight';
import { decodeLegacyHtmlEntities } from './legacyConfigParsing';

interface FunctionInput {
    name: string;
    value: string;
}

interface JavaScriptFunctionEditorProps {
    value: string;
    onChange: (value: string) => void;
    placeholder?: string;
    functionInputs?: FunctionInput[] | string | unknown;
    /** Code language — controls syntax highlighting and header label. */
    language?: string;
}

// Parse function inputs from various formats (array, JSON string, HTML-encoded JSON)
function parseFunctionInputs(value: unknown): FunctionInput[] {
    if (Array.isArray(value)) return value;
    if (typeof value === 'string' && value.trim()) {
        try {
            const decoded = decodeLegacyHtmlEntities(value);
            const parsed = JSON.parse(decoded);
            if (Array.isArray(parsed)) return parsed;
        } catch { /* ignore */ }
    }
    return [];
}

const LANG_CONFIG: Record<string, { ext: () => any; label: string; placeholder: string; comment: string }> = {
    javascript: { ext: () => javascript(), label: 'JavaScript', placeholder: '// Your JavaScript code here', comment: '//' },
    jsx: { ext: () => javascript({ jsx: true, typescript: true }), label: 'JSX / React', placeholder: '// Import React and render your component', comment: '//' },
    html: { ext: () => html(), label: 'HTML', placeholder: '<!-- Your HTML content here -->', comment: '<!--' },
};

export function JavaScriptFunctionEditor({
    value,
    onChange,
    placeholder,
    functionInputs: rawFunctionInputs,
    language = 'javascript',
}: JavaScriptFunctionEditorProps) {
    const functionInputs = parseFunctionInputs(rawFunctionInputs);
    const lang = LANG_CONFIG[language] || LANG_CONFIG.javascript;
    const extraExtensions = useMemo(
        () => (language === 'jsx' || language === 'html') ? [nodeIdHighlighter] : undefined,
        [language],
    );

    const editor = useCodeMirrorEditor({
        value,
        onChange,
        langExtension: lang.ext(),
        placeholderText: placeholder || lang.placeholder,
        tabIndent: '  ',
        extraExtensions,
    });

    const headerContent = (
        <>
            <span className="text-muted-foreground dark:text-zinc-500">{lang.comment} </span>
            <span className="text-yellow-600 dark:text-yellow-400">{lang.label}</span>
            {functionInputs.length > 0 && (
                <>
                    <span className="text-muted-foreground/70 dark:text-zinc-600"> access inputs via </span>
                    <span className="text-orange-700 dark:text-orange-300">
                        {functionInputs.map(input => `inputs.${input.name}`).join(', ')}
                    </span>
                </>
            )}
        </>
    );

    const returnHint = language === 'javascript' ? (
        <>
            <span className="text-purple-400/60">return</span>{' '}
            <span className="text-muted-foreground dark:text-zinc-500">{'{'}key: value{'}'}</span>
        </>
    ) : null;

    const header = (
        <EditorHeader
            isFullscreen={editor.isFullscreen}
            onExpand={editor.handleOpenFullscreen}
            onCollapse={editor.handleCloseFullscreen}
        >
            {headerContent}
        </EditorHeader>
    );

    const footer = <EditorFooter lineCount={editor.lineCount} returnHint={returnHint} />;

    return (
        <EditorShell
            inlineEditorRef={editor.inlineEditorRef}
            fullscreenEditorRef={editor.fullscreenEditorRef}
            isFullscreen={editor.isFullscreen}
            sidebarWidth={editor.sidebarWidth}
            onClose={editor.handleCloseFullscreen}
            header={header}
            footer={footer}
        />
    );
}
