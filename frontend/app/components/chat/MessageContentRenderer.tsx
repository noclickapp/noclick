// Component for rendering message content with inline HTML element tags and context tags
// Parses text to detect HTML code blocks and @mentions, renders them as compact inline tags

import { useMemo, type JSX } from 'react';
import { Code2 } from 'lucide-react';
import { cn } from '~/lib/utils';

interface MessageContentRendererProps {
    text: string;
    className?: string;
}

// Component for inline HTML element tag display in messages
const HtmlElementTag = ({ tagName, html, noclickId }: { tagName: string; html: string; noclickId?: string }) => {
    const handleMouseEnter = () => {
        if (noclickId) {
            document.dispatchEvent(new CustomEvent('noclick:highlight-element', {
                detail: { noclickId }
            }));
        }
    };

    const handleMouseLeave = () => {
        if (noclickId) {
            document.dispatchEvent(new CustomEvent('noclick:unhighlight-element'));
        }
    };

    return (
        <span
            className={cn(
                "inline",
                "bg-foreground/80 rounded px-1 border border-primary/70",
                "transition-all duration-150",
                "hover:bg-foreground/90 hover:border-primary/80 cursor-default",
                "text-xs text-primary-foreground font-mono"
            )}
            style={{
                marginLeft: '2px',
                marginRight: '2px',
                verticalAlign: 'baseline',
                padding: '0 4px'
            }}
            title={`HTML ${tagName} element`}
            onMouseEnter={handleMouseEnter}
            onMouseLeave={handleMouseLeave}
        >
            &lt;{tagName.toLowerCase()}&gt;
        </span>
    );
};

// Component for inline context tag display in messages
const ContextTag = ({ value }: { value: string }) => {
    return (
        <span
            className={cn(
                "inline-flex items-center",
                "bg-foreground/80 rounded px-1 border border-primary/70",
                "transition-all duration-150",
                "hover:bg-foreground/90 hover:border-primary/80 cursor-default"
            )}
            style={{
                marginLeft: '2px',
                marginRight: '2px',
                verticalAlign: 'middle'
            }}
            title={`Context: ${value}`}
        >
            <span className="text-xs text-blue-600 dark:text-blue-400 dark:text-blue-600 font-medium">@</span>
            <span className="text-xs text-primary-foreground">{value}</span>
        </span>
    );
};

export function MessageContentRenderer({ text, className }: MessageContentRendererProps) {
    const renderedContent = useMemo(() => {
        // Combined pattern to match both HTML blocks and context tags
        const combinedPattern = /(```html(?:\[([^\]]+)\])?\n([\s\S]*?)\n```)|(@\[([^\]]+)\])/g;

        const parts: (string | JSX.Element)[] = [];
        let lastIndex = 0;
        let keyIndex = 0;
        let match;

        while ((match = combinedPattern.exec(text)) !== null) {
            // Add text before the match
            if (match.index > lastIndex) {
                const textBefore = text.slice(lastIndex, match.index);
                if (textBefore) {
                    parts.push(textBefore);
                }
            }

            // Check if it's an HTML block or context tag
            if (match[1]) {
                // HTML code block
                const noclickIdFromMarker = match[2];
                const htmlContent = match[3];
                let tagName = 'html';
                let noclickId: string | undefined = noclickIdFromMarker;

                // Extract tag name
                const tagMatch = htmlContent.match(/<(\w+)[^>]*>/);
                if (tagMatch) {
                    tagName = tagMatch[1].toLowerCase();
                }

                // Try to extract noclickId from HTML if not in marker
                if (!noclickId) {
                    const dataAttrMatch = htmlContent.match(/data-noclick-id=["']([^"']+)["']/);
                    if (dataAttrMatch) {
                        noclickId = dataAttrMatch[1];
                    }
                }

                parts.push(
                    <HtmlElementTag
                        key={`html-tag-${keyIndex++}`}
                        tagName={tagName}
                        html={htmlContent}
                        noclickId={noclickId}
                    />
                );
            } else if (match[4]) {
                // Context tag
                const contextValue = match[5];
                parts.push(
                    <ContextTag
                        key={`context-tag-${keyIndex++}`}
                        value={contextValue}
                    />
                );
            }

            lastIndex = match.index + match[0].length;
        }

        // Add remaining text
        if (lastIndex < text.length) {
            parts.push(text.slice(lastIndex));
        }

        // If no special content found, return original text
        if (parts.length === 0) {
            return text;
        }

        return parts;
    }, [text]);

    // If renderedContent is a string, just return it directly
    if (typeof renderedContent === 'string') {
        return <span className={cn("whitespace-pre-wrap break-words overflow-wrap-anywhere", className)}>{renderedContent}</span>;
    }

    // Otherwise render the mixed content inline
    return (
        <span className={cn("whitespace-pre-wrap break-words overflow-wrap-anywhere", className)}>
            {renderedContent}
        </span>
    );
}
