// MarkdownRenderer component for rendering markdown with syntax highlighting and mermaid support
// Provides themed markdown rendering with custom components for code blocks, links, and diagrams

import { Children, Fragment, useEffect, useRef, useState, memo, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import remarkYoutube from '~/lib/remark-youtube';
import rehypeRaw from 'rehype-raw';
import rehypeSanitize, { defaultSchema } from 'rehype-sanitize';
import rehypeKatex from 'rehype-katex';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { oneDark } from 'react-syntax-highlighter/dist/cjs/styles/prism';
import panzoom from 'panzoom';
import { cn } from '~/lib/utils';
import { Copy, Check } from 'lucide-react';
import { renderMermaidDiagram, initializeMermaid } from './mermaid/renderDiagram';
import 'katex/dist/katex.min.css';

export interface MarkdownRendererProps {
    content: string;
    className?: string;
    variant?: 'default' | 'sticky-note';
    /** When true, suppress `<hr>` rules. Useful for template descriptions
     *  where authored `---` separators clutter what's otherwise a short blurb. */
    hideHorizontalRules?: boolean;
    /** Streaming cursor node. When set, the renderer appends an invisible
     *  sentinel to `content` and the `p`/`li` overrides replace it with this
     *  node, so the cursor lands inline at the very tail of the rendered
     *  text run instead of as a block-level sibling below the markdown. */
    cursor?: ReactNode;
    /** Open handler for links whose href is a SANDBOX FILE PATH (an agent
     *  writing "[Report](/workspace/report.md)"). Matched links render as a
     *  file chip calling this instead of an anchor — a real anchor navigates
     *  the router to a 404. Without the handler, matched links still render
     *  as inert chips so they're never dead navigation. */
    onSandboxPathClick?: (path: string) => void;
    /** Treat single newlines as hard line breaks (GFM "breaks" mode). For
     *  surfaces showing agent RESPONSE text that previously rendered with
     *  whitespace-pre-wrap (run results popup): plain-text replies rely on
     *  bare \n, which standard markdown would collapse into one paragraph. */
    breaks?: boolean;
}

/** Minimal remark-breaks: split text nodes on single newlines into hard
 *  `break` nodes. AST-level, so code blocks / inline code are untouched.
 *  Hand-rolled because this checkout's pnpm store mismatch blocks adding the
 *  real remark-breaks dep — the transform is identical for our needs. */
function remarkHardBreaks() {
    type MdNode = { type: string; value?: string; children?: MdNode[] };
    const visit = (node: MdNode) => {
        if (!node.children) return;
        node.children = node.children.flatMap((child): MdNode[] => {
            visit(child);
            if (child.type !== 'text' || !child.value?.includes('\n')) return [child];
            const out: MdNode[] = [];
            child.value.split('\n').forEach((part, i) => {
                if (i > 0) out.push({ type: 'break' });
                if (part) out.push({ type: 'text', value: part });
            });
            return out;
        });
    };
    return (tree: unknown) => visit(tree as MdNode);
}

// Absolute POSIX paths under the roots agent sandboxes actually use. Kept
// tight so app-internal links (e.g. /dashboard) are never intercepted.
const SANDBOX_PATH_RE = /^\/(workspace|root|tmp|home|mnt|data|srv|var|opt|etc|usr)\//;

export function isSandboxFilePath(href: string | undefined): href is string {
    return !!href && SANDBOX_PATH_RE.test(href);
}

/** The one rendering for a sandbox file reference in agent markdown — used by
 *  both the anchor override (`[Report](/workspace/x.md)`) and the inline-code
 *  override (`` `/workspace/x.md` ``, the more common model idiom). With a
 *  handler it opens the workspace preview; without one it stays inert (never
 *  dead navigation). */
function SandboxPathChip({
    path,
    mono,
    onClick,
    children,
}: {
    path: string;
    mono?: boolean;
    onClick?: (path: string) => void;
    children: ReactNode;
}) {
    return (
        <button
            type="button"
            title={path}
            data-testid="markdown-sandbox-path"
            onClick={onClick ? () => onClick(path) : undefined}
            className={cn(
                'inline-flex max-w-full items-center gap-1 align-baseline rounded-md border border-border bg-foreground/[0.04] px-1.5 py-0.5 text-foreground/90',
                mono ? 'font-mono text-sm' : 'text-[0.92em]',
                onClick
                    ? 'hover:bg-foreground/[0.09] hover:text-foreground transition-colors cursor-pointer'
                    : 'cursor-default',
            )}
        >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-[0.9em] w-[0.9em] shrink-0 opacity-70"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/></svg>
            <span className="truncate">{children}</span>
        </button>
    );
}

// Private-use Unicode codepoint — won't collide with real content and isn't
// stripped by rehypeSanitize. Appended to `content` when `cursor` is set;
// `injectCursor` swaps it out for the cursor React node.
const CURSOR_SENTINEL = '';

function injectCursor(children: ReactNode, cursor: ReactNode): ReactNode {
    let replaced = false;
    const out = Children.map(children, (child) => {
        if (replaced) return child;
        if (typeof child === 'string' && child.includes(CURSOR_SENTINEL)) {
            replaced = true;
            const [before, after = ''] = child.split(CURSOR_SENTINEL);
            return (
                <Fragment>
                    {before}
                    {cursor}
                    {after}
                </Fragment>
            );
        }
        return child;
    });
    return replaced ? out : children;
}

// Sanitization schema: Allow YouTube iframes while blocking XSS vectors
const sanitizeSchema = {
    ...defaultSchema,
    tagNames: [...(defaultSchema.tagNames || []), 'iframe'],
    attributes: {
        ...defaultSchema.attributes,
        // Allow YouTube iframe with specific attributes
        div: [
            ...(defaultSchema.attributes?.div || []),
            ['className', 'youtube-embed-wrapper'],
            ['style'],
        ],
        iframe: [
            'src',
            'width',
            'height',
            'frameBorder',
            'allow',
            'allowFullScreen',
            ['style'],
        ],
    },
    protocols: {
        ...defaultSchema.protocols,
        // Only allow https for iframe src (YouTube embeds)
        src: ['https'],
    },
};

// MermaidDiagram component with popup - memoized to prevent re-renders when props unchanged
const MermaidDiagram = memo(function MermaidDiagram({ definition, variant = 'default' }: { definition: string; variant?: 'default' | 'sticky-note' }) {
    const [isOpen, setIsOpen] = useState(false);
    const diagramRef = useRef<HTMLDivElement>(null);
    const popupRef = useRef<HTMLDivElement>(null);
    const panzoomInstanceRef = useRef<ReturnType<typeof panzoom> | null>(null);
    const lastRenderedDefinitionRef = useRef<string | null>(null);

    // Initialize mermaid on first mount
    useEffect(() => {
        initializeMermaid();
    }, []);

    // Simplified rendering using the unified function
    const renderDiagram = async (container: HTMLDivElement, isPopup: boolean = false) => {
        try {
            // Use the new unified rendering function
            await renderMermaidDiagram(container, definition, isPopup);

            // Set pointer events for inline diagrams
            if (!isPopup) {
                const svgElement = container.querySelector('svg');
                if (svgElement) {
                    // Make all child elements non-interactive for inline view
                    svgElement.style.pointerEvents = 'none';
                    const allElements = svgElement.querySelectorAll('*');
                    allElements.forEach(el => {
                        (el as HTMLElement).style.pointerEvents = 'none';
                    });
                }
            }
        } catch (error) {
            // Error handling is already done in renderMermaidDiagram
            console.error('Diagram rendering error:', error);
        }
    };

    useEffect(() => {
        const renderInlineDiagram = async () => {
            if (!diagramRef.current || !definition) {
                return;
            }

            // Skip rendering if this exact definition was already rendered AND the container still has content
            if (lastRenderedDefinitionRef.current === definition && diagramRef.current.querySelector('svg')) {
                return;
            }

            await renderDiagram(diagramRef.current, false);
            // Track that we've rendered this definition
            lastRenderedDefinitionRef.current = definition;
        };
        renderInlineDiagram();
    }, [definition]);

    useEffect(() => {
        const renderPopupDiagram = async () => {
            if (popupRef.current && isOpen && definition) {
                await renderDiagram(popupRef.current, true);

                // Initialize panzoom after rendering is complete
                const svgElement = popupRef.current.querySelector('svg') as SVGElement;
                if (svgElement) {
                    // Destroy previous instance if it exists
                    if (panzoomInstanceRef.current) {
                        panzoomInstanceRef.current.dispose();
                    }

                    // Initialize panzoom on the SVG element
                    panzoomInstanceRef.current = panzoom(svgElement, {
                        maxZoom: 5,
                        minZoom: 0.3,
                        initialZoom: 1,
                        bounds: false,
                        boundsPadding: 0.1,
                        zoomDoubleClickSpeed: 1,
                        smoothScroll: false,
                        // Prevent browser zoom when scrolling
                        beforeWheel: function() {
                            // Allow zooming without modifier key
                            // This prevents the default browser zoom
                            return false; // false means "don't ignore this event"
                        },
                        // Prevent browser zoom with pinch gestures
                        onTouch: function() {
                            // Don't prevent default to allow pinch zoom
                            return false;
                        }
                    });
                }
            }
        };

        renderPopupDiagram();

        return () => {
            // Clean up panzoom instance when closing popup
            if (panzoomInstanceRef.current) {
                panzoomInstanceRef.current.dispose();
                panzoomInstanceRef.current = null;
            }
        };
    }, [isOpen, definition]);

    return (
        <>
            <div
                className={cn(
                    "mermaid my-2 rounded-lg overflow-hidden relative group cursor-pointer",
                    variant === 'sticky-note' ? "bg-transparent" : "bg-[#1a1a1a]"
                )}
                data-type="mermaid"
                style={variant === 'sticky-note' ? {
                    ['--mermaid-node-fill' as string]: 'rgba(255, 255, 255, 0.15)',
                    ['--mermaid-node-stroke' as string]: 'rgba(0, 0, 0, 0.2)',
                    ['--mermaid-text-fill' as string]: 'rgba(0, 0, 0, 0.5)',
                    ['--mermaid-edge-label-bg' as string]: 'rgba(255, 255, 255, 0.4)',
                } : undefined}
                title="Click to expand diagram"
                role="button"
                tabIndex={0}
                onClick={() => setIsOpen(true)}
                onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault();
                        setIsOpen(true);
                    }
                }}
                aria-label="Click to expand Mermaid diagram"
            >

                {/* Visual hover feedback */}
                <div className={cn(
                    "absolute inset-0 bg-white/0 rounded-lg transition-colors pointer-events-none z-[2]",
                    variant === 'sticky-note' ? "group-hover:bg-white/[0.02]" : "group-hover:bg-muted dark:group-hover:bg-white/5"
                )} />

                {/* Expand icon indicator */}
                <div className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity z-[3] pointer-events-none">
                    <svg width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
                        <path d="M6 14L14 6M14 6H8M14 6V12" stroke="#e2e8f0" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
                    </svg>
                </div>

                {/* Mermaid content container */}
                <div
                    ref={diagramRef}
                    className="relative p-4 min-h-[100px] flex items-center justify-center pointer-events-none"
                />
            </div>

            {/* Popup Modal - Rendered via Portal */}
            {isOpen && typeof document !== 'undefined' && createPortal(
                <div
                    className="fixed inset-0 z-[9999] flex items-center justify-center p-8 bg-black/80 backdrop-blur-sm"
                    onClick={() => setIsOpen(false)}
                    onWheel={(e) => {
                        // Prevent browser zoom when scrolling on the modal backdrop
                        if (e.ctrlKey || e.metaKey) {
                            e.preventDefault();
                        }
                    }}
                >
                    <div
                        className="relative w-[70vw] h-[70vh] bg-[#1a1a1a] rounded-lg border border-[#333333] flex flex-col"
                        onClick={(e) => e.stopPropagation()}
                        onWheel={(e) => {
                            // Prevent browser zoom when scrolling on the modal
                            if (e.ctrlKey || e.metaKey) {
                                e.preventDefault();
                            }
                        }}
                    >
                        {/* Circular close button */}
                        <button
                            onClick={() => setIsOpen(false)}
                            className="absolute top-4 right-4 p-2 rounded-full bg-[#2E2E2E] hover:bg-[#333333] text-gray-400 hover:text-white transition-all z-10"
                            aria-label="Close diagram"
                        >
                            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                            </svg>
                        </button>

                        {/* Container for the diagram with panzoom */}
                        <div
                            className="flex-1 overflow-hidden relative"
                            style={{
                                cursor: 'grab',
                                touchAction: 'none' // Prevent browser gestures
                            }}
                        >
                            <div
                                ref={popupRef}
                                className="w-full h-full flex items-center justify-center mermaid-popup-container"
                            />
                        </div>
                    </div>
                </div>,
                document.body
            )}
        </>
    );
});

// CodeBlock component with copy button
function CodeBlock({ language, value }: { language: string; value: string }) {
    const [copied, setCopied] = useState(false);

    const handleCopy = async () => {
        try {
            await navigator.clipboard.writeText(value);
            setCopied(true);
            setTimeout(() => setCopied(false), 2000);
        } catch (err) {
            console.error('Failed to copy:', err);
        }
    };

    return (
        <div className="relative group">
            <button
                onClick={handleCopy}
                className="absolute top-2 right-2 p-1.5 rounded-md bg-[#1a1a1a] hover:bg-[#333333] text-gray-400 hover:text-white transition-all opacity-0 group-hover:opacity-100 z-10"
                aria-label="Copy code"
            >
                {copied ? (
                    <Check className="h-4 w-4 text-foreground" />
                ) : (
                    <Copy className="h-4 w-4" />
                )}
            </button>
            <SyntaxHighlighter
                style={oneDark}
                language={language || 'text'}
                PreTag="div"
                customStyle={{
                    margin: '0.25rem 0',
                    borderRadius: '0.375rem',
                    fontSize: '0.8125rem',
                    backgroundColor: '#2E2E2E',
                    padding: '0.75rem 3rem 0.75rem 1rem', // Reduced padding, kept space for copy button
                    lineHeight: '1.4',
                }}
                codeTagProps={{
                    style: {
                        fontFamily: 'ui-monospace, SFMono-Regular, "SF Mono", Consolas, "Liberation Mono", Menlo, monospace',
                    }
                }}
            >
                {value}
            </SyntaxHighlighter>
        </div>
    );
}

const MarkdownRendererComponent = function({ content, className, variant = 'default', hideHorizontalRules = false, cursor, onSandboxPathClick, breaks = false }: MarkdownRendererProps) {
    // Append the sentinel only while streaming. ReactMarkdown will land it
    // inside the last inline-text element (typically the final <p> or <li>),
    // and the `p`/`li` overrides swap it for the cursor node.
    const renderedContent = cursor ? content + CURSOR_SENTINEL : content;
    const containerRef = useRef<HTMLDivElement>(null);

    // Check if content is simple text (no markdown formatting)
    // Only check for clear markdown patterns to avoid false positives
    const isSimpleText = !content.includes('\n\n') &&          // No paragraphs
                        !content.includes('```') &&            // No code blocks
                        !content.includes('**') &&             // No bold
                        !/\*[^*\s]+\*/.test(content) &&       // No italic (but allow lone asterisks)
                        !content.match(/^#+\s/m) &&           // No headers
                        !content.match(/^[-*+]\s/m) &&        // No unordered lists
                        !content.match(/^\d+\.\s/m) &&        // No ordered lists
                        !content.includes('](') &&            // No links
                        !content.match(/^>/m) &&              // No blockquotes
                        !content.includes(' | ') &&           // No tables
                        !content.includes('$') &&             // No math (inline or display)
                        !content.includes('\\[') &&           // No display math
                        !content.includes('\\(');             // No inline math

    // Note: Mermaid rendering is now handled by the MermaidDiagram component

    return (
        <div ref={containerRef} className={cn(
            "markdown-content [&>*:last-child]:mb-0 [&>*:first-child]:mt-0",
            // KaTeX math styling for dark theme
            "[&_.katex]:text-foreground [&_.katex-display]:my-2",
            className
        )}>
            {/* singleDollarTextMath OFF: chat text is full of literal dollars
                ("A$AP Rocky … A$AP" turned everything between them into KaTeX,
                2026-07-19). Math still renders via $$…$$. */}
            <ReactMarkdown
                remarkPlugins={breaks
                    ? [remarkGfm, [remarkMath, { singleDollarTextMath: false }], remarkYoutube, remarkHardBreaks]
                    : [remarkGfm, [remarkMath, { singleDollarTextMath: false }], remarkYoutube]}
                rehypePlugins={[rehypeRaw, [rehypeSanitize, sanitizeSchema], rehypeKatex]}
                components={{
                    // Headings
                    h1: ({ children }) => (
                        <h1 className="text-2xl font-bold mb-2 first:mt-0 mt-3 text-foreground">{children}</h1>
                    ),
                    h2: ({ children }) => (
                        <h2 className="text-xl font-semibold mb-2 first:mt-0 mt-3 text-foreground">{children}</h2>
                    ),
                    h3: ({ children }) => (
                        <h3 className="text-lg font-semibold mb-1.5 first:mt-0 mt-2.5 text-foreground">{children}</h3>
                    ),
                    h4: ({ children }) => (
                        <h4 className="text-base font-semibold mb-1.5 first:mt-0 mt-2 text-foreground">{children}</h4>
                    ),

                    // Paragraphs and text
                    p: ({ children }) => (
                        <p className={cn(
                            "text-foreground/80 leading-relaxed",
                            isSimpleText ? "mb-0" : "mb-1.5"
                        )}>{cursor ? injectCursor(children, cursor) : children}</p>
                    ),
                    strong: ({ children }) => (
                        <strong className="font-bold text-foreground">{children}</strong>
                    ),
                    em: ({ children }) => (
                        <em className="italic text-foreground/80">{children}</em>
                    ),

                    // Lists
                    ul: ({ children }) => (
                        <ul className="list-disc list-outside mb-1.5 space-y-0.5 text-foreground/80 ml-6">{children}</ul>
                    ),
                    ol: ({ children }) => (
                        <ol className="list-decimal list-outside mb-1.5 space-y-0.5 text-foreground/80 ml-6">{children}</ol>
                    ),
                    li: ({ children }) => (
                        <li className="text-foreground/80">{cursor ? injectCursor(children, cursor) : children}</li>
                    ),

                    // Links. Sandbox file paths never render as anchors — an
                    // anchor to /workspace/report.md navigates the router to a
                    // 404 (2026-07-17 incident); with a handler they open the
                    // workspace file preview, without one they're inert.
                    a: ({ href, children }) => {
                        if (isSandboxFilePath(href)) {
                            return (
                                <SandboxPathChip path={href} onClick={onSandboxPathClick}>
                                    {children}
                                </SandboxPathChip>
                            );
                        }
                        return (
                            <a
                                href={href}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="text-foreground hover:text-foreground/80 underline transition-colors"
                            >
                                {children}
                            </a>
                        );
                    },

                    // Blockquotes
                    blockquote: ({ children }) => (
                        <blockquote className="border-l-4 border-border dark:border-gray-600 pl-4 my-2 italic text-muted-foreground">
                            {children}
                        </blockquote>
                    ),

                    // Horizontal rules — caller can opt out (e.g. template descriptions
                    // where authored `---` separators clutter a short summary blurb).
                    hr: hideHorizontalRules ? () => null : () => (
                        <hr className="my-2 border-border dark:border-gray-700" />
                    ),

                    // Tables (from GFM)
                    table: ({ children }) => (
                        <div className="overflow-x-auto mb-2 rounded-lg border border-border">
                            <table className="min-w-full">
                                {children}
                            </table>
                        </div>
                    ),
                    thead: ({ children }) => (
                        <thead className="bg-muted">{children}</thead>
                    ),
                    tbody: ({ children }) => (
                        <tbody className="divide-y divide-border">{children}</tbody>
                    ),
                    tr: ({ children }) => (
                        <tr className="hover:bg-muted/50 transition-colors">{children}</tr>
                    ),
                    th: ({ children }) => (
                        <th className="px-4 py-2 text-left text-foreground font-semibold">{children}</th>
                    ),
                    td: ({ children }) => (
                        <td className="px-4 py-2 text-foreground/80">{children}</td>
                    ),

                    // Pre blocks - wrap code blocks
                    pre: ({ children, ...props }: any) => {
                        // Extract the code element from children
                        const codeElement = children?.props;

                        if (!codeElement) {
                            return <pre {...props}>{children}</pre>;
                        }

                        const className = codeElement.className || '';
                        const match = /language-(\w+)/.exec(className);
                        const language = match ? match[1] : '';
                        const codeContent = String(codeElement.children).replace(/\n$/, '');

                        // Check if this is a mermaid block
                        if (language === 'mermaid') {
                            return <MermaidDiagram definition={codeContent} variant={variant} />;
                        }

                        // Regular code blocks with syntax highlighting
                        return (
                            <CodeBlock
                                language={language}
                                value={codeContent}
                            />
                        );
                    },

                    // Code - only handle inline code
                    code: ({ className, children, ...props }: any) => {
                        // This will only be called for inline code
                        // Block code is intercepted by the pre component
                        //
                        // A backticked sandbox path (`/workspace/report.md` —
                        // the way models most often reference the files they
                        // write) becomes a clickable preview chip when a
                        // handler is wired; plain code otherwise.
                        const text = String(children).trim();
                        if (onSandboxPathClick && isSandboxFilePath(text)) {
                            return (
                                <SandboxPathChip path={text} mono onClick={onSandboxPathClick}>
                                    {text}
                                </SandboxPathChip>
                            );
                        }
                        return (
                            <code className="px-1.5 py-0.5 bg-muted text-foreground/80 rounded text-sm font-mono" {...props}>
                                {children}
                            </code>
                        );
                    },

                    // Images
                    img: ({ src, alt }) => (
                        <img
                            src={src}
                            alt={alt}
                            className="max-w-full h-auto rounded-lg my-2"
                        />
                    ),
                }}
            >
                {renderedContent}
            </ReactMarkdown>
        </div>
    );
};

export const MarkdownRenderer = memo(MarkdownRendererComponent);
