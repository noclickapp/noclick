// Python function body editor with syntax highlighting for the serverless function node.
// Shows a dynamic function signature header based on defined inputs.
// Uses CodeMirror 6 via shared useCodeMirrorEditor hook.

import { python } from '@codemirror/lang-python';
import { useCodeMirrorEditor, EditorHeader, EditorFooter, EditorShell } from './useCodeMirrorEditor';

interface PythonFunctionEditorProps {
    value: string;
    onChange: (value: string) => void;
    placeholder?: string;
    inputNames?: string[];
}

export function PythonFunctionEditor({ value, onChange, placeholder, inputNames = [] }: PythonFunctionEditorProps) {
    const editor = useCodeMirrorEditor({
        value,
        onChange,
        langExtension: python(),
        placeholderText: placeholder || '# Your Python code here',
        tabIndent: '    ',
    });

    const headerContent = (
        <>
            <span className="text-purple-600 dark:text-purple-400">def</span>
            <span className="text-blue-700 dark:text-blue-300 ml-1">run</span>
            <span className="text-muted-foreground">(</span>
            {inputNames.length > 0 ? (
                inputNames.map((name, idx) => (
                    <span key={name}>
                        <span className="text-orange-700 dark:text-orange-300">{name}</span>
                        {idx < inputNames.length - 1 && <span className="text-muted-foreground dark:text-zinc-500">, </span>}
                    </span>
                ))
            ) : (
                <span className="text-muted-foreground/70 dark:text-zinc-600 italic text-[11px]">no inputs</span>
            )}
            <span className="text-muted-foreground">):</span>
        </>
    );

    const returnHint = (
        <>
            <span className="text-purple-400/60">return</span>{' '}
            <span className="text-muted-foreground dark:text-zinc-500">{'{'}'key': value{'}'}</span>
        </>
    );

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
