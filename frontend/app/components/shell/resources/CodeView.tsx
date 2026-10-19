// Code and documents the way a repo shows them: highlighted source with line
// numbers in the app's own syntax colours (the --code-* tokens, so light and
// dark both read like GitHub), and markdown rendered as a page, its fenced
// blocks highlighted the same way.
import type { CSSProperties } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { cn } from '~/lib/utils';

const token = (name: string): CSSProperties => ({ color: `hsl(var(--code-${name}))` });

export const CODE_BASE: CSSProperties = {
    color: 'hsl(var(--foreground) / 0.9)',
    background: 'none',
    fontFamily: 'ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace',
    textAlign: 'left',
    whiteSpace: 'pre',
    wordSpacing: 'normal',
    wordBreak: 'normal',
    tabSize: 2,
    hyphens: 'none',
};

export const CODE_THEME: Record<string, CSSProperties> = {
    'code[class*="language-"]': CODE_BASE,
    'pre[class*="language-"]': { ...CODE_BASE, margin: 0, overflow: 'auto' },
    comment: { ...token('comment'), fontStyle: 'italic' },
    prolog: token('comment'),
    doctype: token('comment'),
    cdata: token('comment'),
    punctuation: token('punctuation'),
    property: token('number'),
    tag: token('tag'),
    boolean: token('number'),
    number: token('number'),
    constant: token('number'),
    symbol: token('number'),
    deleted: token('keyword'),
    selector: token('tag'),
    'attr-name': token('number'),
    string: token('string'),
    char: token('string'),
    builtin: token('variable'),
    inserted: token('tag'),
    operator: token('keyword'),
    entity: token('number'),
    url: token('string'),
    atrule: token('keyword'),
    'attr-value': token('string'),
    keyword: token('keyword'),
    function: token('function'),
    'class-name': token('variable'),
    regex: token('string'),
    important: { ...token('keyword'), fontWeight: 600 },
    variable: token('variable'),
    'template-string': token('string'),
    interpolation: token('punctuation'),
};

const LANGUAGES: Record<string, string> = {
    ts: 'typescript',
    tsx: 'tsx',
    js: 'javascript',
    jsx: 'jsx',
    mjs: 'javascript',
    json: 'json',
    css: 'css',
    html: 'markup',
    md: 'markdown',
    mdx: 'markdown',
    yml: 'yaml',
    yaml: 'yaml',
    sh: 'bash',
    bash: 'bash',
    py: 'python',
    sql: 'sql',
    toml: 'toml',
};

export function languageFor(path: string): string {
    const ext = path.includes('.') ? path.slice(path.lastIndexOf('.') + 1).toLowerCase() : '';
    return LANGUAGES[ext] ?? 'text';
}

export function CodeView({ code, language, lineNumbers = true, className }: { code: string; language: string; lineNumbers?: boolean; className?: string }) {
    return (
        <div className={cn('overflow-x-auto scrollbar-subtle', className)}>
            <SyntaxHighlighter
                language={language}
                style={CODE_THEME}
                showLineNumbers={lineNumbers}
                lineNumberStyle={{ minWidth: '3.5em', paddingRight: '1.25em', textAlign: 'right', color: 'hsl(var(--muted-foreground) / 0.5)', fontStyle: 'normal', userSelect: 'none' }}
                customStyle={{ margin: 0, padding: lineNumbers ? '14px 20px 14px 0' : '14px 16px', background: 'transparent', fontSize: 13, lineHeight: 1.7 }}
                codeTagProps={{ style: { fontFamily: CODE_BASE.fontFamily } }}
            >
                {code.replace(/\n$/, '')}
            </SyntaxHighlighter>
        </div>
    );
}

/** A README-style page: front matter becomes the title, fenced code is highlighted. */
export function MarkdownDoc({ source, className }: { source: string; className?: string }) {
    const front = /^---\n([\s\S]*?)\n---\n?/.exec(source);
    const title = front ? /^title:\s*(.+)$/m.exec(front[1])?.[1] : undefined;
    const body = front ? source.slice(front[0].length) : source;
    return (
        <div
            className={cn(
                'prose prose-sm max-w-none text-[14.5px] leading-relaxed text-foreground/90 dark:prose-invert',
                'prose-headings:font-semibold prose-headings:tracking-[-0.01em] prose-headings:text-foreground prose-h1:text-[22px] prose-h2:mt-7 prose-h2:border-b prose-h2:border-border prose-h2:pb-2 prose-h2:text-[17px] dark:prose-h2:border-foreground/[0.08]',
                'prose-p:text-foreground/85 prose-li:text-foreground/85 prose-strong:text-foreground prose-a:text-foreground prose-a:underline-offset-[3px]',
                'prose-code:rounded-md prose-code:bg-foreground/[0.07] prose-code:px-1.5 prose-code:py-0.5 prose-code:text-[0.86em] prose-code:font-normal prose-code:text-foreground prose-code:before:content-none prose-code:after:content-none',
                'prose-pre:my-4 prose-pre:rounded-xl prose-pre:bg-foreground/[0.04] prose-pre:p-0 prose-pre:ring-1 prose-pre:ring-inset prose-pre:ring-foreground/[0.06]',
                className
            )}
        >
            {title && <h1>{title}</h1>}
            <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={{
                    pre: ({ children }) => <pre>{children}</pre>,
                    code: ({ className: lang, children }) => {
                        const match = /language-(\w+)/.exec(lang ?? '');
                        const text = String(children);
                        if (!match && !text.includes('\n')) return <code>{children}</code>;
                        return <CodeView code={text} language={match?.[1] ?? 'text'} lineNumbers={false} className="not-prose" />;
                    },
                }}
            >
                {body}
            </ReactMarkdown>
        </div>
    );
}
