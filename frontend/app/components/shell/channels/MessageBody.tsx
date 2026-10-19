// A message's words as markdown: bold, italic, strike, code, quotes, lists and
// links, with @mentions in the member's colour (yours highlighted) and
// #channels opening the channel. Mentions and channels are found in the text
// nodes only, so a `@name` inside code stays code.
import { useMemo } from 'react';
import ReactMarkdown, { defaultUrlTransform, type Components, type Options } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { SKIP, visit } from 'unist-util-visit';
import type { PhrasingContent, Root } from 'mdast';
import { cn } from '~/lib/utils';
import { MENTION_HUE } from './avatars';
import { YOU_ID } from './model';
import type { ChannelMember } from './types';

const MENTION = 'nc-mention:';
const CHANNEL = 'nc-channel:';

interface RefOptions {
    names: string[];
    /** The workspace's channels by name. */
    channels: ReadonlyMap<string, string>;
}

const escape = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

/** Turns `@Name` and `#channel` in text into links the renderer draws as mentions. */
function remarkChannelRefs({ names, channels }: RefOptions) {
    // Longest first, so "@Sam" never cuts "@Samira" short.
    const people = [...names].sort((a, b) => b.length - a.length).map(escape);
    const pattern = new RegExp(`(${[people.length ? `@(?:${people.join('|')})\\b` : '', '#[a-z0-9][a-z0-9-]*'].filter(Boolean).join('|')})`, 'g');
    return (tree: Root) => {
        visit(tree, 'text', (node, index, parent) => {
            if (!parent || index === undefined || parent.type === 'link' || parent.type === 'linkReference') return;
            const parts = node.value.split(pattern);
            if (parts.length === 1) return;
            const nodes: PhrasingContent[] = parts.filter(Boolean).map((part) => {
                const ref =
                    part.startsWith('@') && names.includes(part.slice(1))
                        ? `${MENTION}${encodeURIComponent(part.slice(1))}`
                        : part.startsWith('#') && channels.has(part.slice(1))
                          ? `${CHANNEL}${part.slice(1)}`
                          : null;
                return ref ? { type: 'link', url: ref, children: [{ type: 'text', value: part }] } : { type: 'text', value: part };
            });
            (parent.children as PhrasingContent[]).splice(index, 1, ...nodes);
            return [SKIP, index + nodes.length];
        });
    };
}

const keepRefs = (url: string) => (url.startsWith(MENTION) || url.startsWith(CHANNEL) ? url : defaultUrlTransform(url));

export function MessageBody({
    text,
    members,
    channels,
    onChannel,
    muted,
}: {
    text: string;
    members: ChannelMember[];
    /** The workspace's channels by name, so `#name` opens one. */
    channels: ReadonlyMap<string, string>;
    onChannel: (id: string) => void;
    /** An event line ("set the topic: …") reads quieter than speech. */
    muted?: boolean;
}) {
    const plugins = useMemo((): Options['remarkPlugins'] => [remarkGfm, [remarkChannelRefs, { names: members.map((m) => m.name), channels }]], [members, channels]);
    const components = useMemo((): Components => {
        const byName = new Map(members.map((m) => [m.name, m]));
        const heading: Components['p'] = ({ children }) => <p className="font-semibold text-foreground">{children}</p>;
        return {
            p: ({ children }) => <p className="whitespace-pre-wrap">{children}</p>,
            h1: heading,
            h2: heading,
            h3: heading,
            h4: heading,
            h5: heading,
            h6: heading,
            strong: ({ children }) => <strong className="font-semibold text-foreground">{children}</strong>,
            del: ({ children }) => <del className="text-foreground/55 decoration-foreground/45">{children}</del>,
            ul: ({ children }) => <ul className="list-disc space-y-0.5 pl-5 marker:text-foreground/40">{children}</ul>,
            ol: ({ children }) => <ol className="list-decimal space-y-0.5 pl-5 marker:text-foreground/50">{children}</ol>,
            blockquote: ({ children }) => <blockquote className="border-l-[3px] border-foreground/20 pl-3 text-foreground/75 [&>*+*]:mt-1">{children}</blockquote>,
            pre: ({ children }) => (
                <pre className="overflow-x-auto rounded-xl bg-foreground/[0.04] px-3.5 py-3 font-mono text-[13px] leading-relaxed ring-1 ring-inset ring-foreground/[0.07] scrollbar-subtle [&>code]:bg-transparent [&>code]:p-0 [&>code]:text-[13px]">
                    {children}
                </pre>
            ),
            code: ({ children }) => <code className="rounded-[5px] bg-foreground/[0.08] px-[5px] py-px font-mono text-[0.86em] text-foreground">{children}</code>,
            hr: () => <hr className="border-border dark:border-foreground/[0.1]" />,
            a: ({ href = '', children }) => {
                if (href.startsWith(MENTION)) {
                    const member = byName.get(decodeURIComponent(href.slice(MENTION.length)));
                    if (member?.id === YOU_ID) return <span className="rounded-[5px] bg-foreground/[0.1] px-1 py-px font-medium text-foreground">{children}</span>;
                    return <span className={cn('font-medium', member?.hue ? MENTION_HUE[member.hue] : 'text-foreground')}>{children}</span>;
                }
                if (href.startsWith(CHANNEL)) {
                    return (
                        <button
                            type="button"
                            onClick={() => {
                                const id = channels.get(href.slice(CHANNEL.length));
                                if (id) onChannel(id);
                            }}
                            className="font-medium text-foreground underline decoration-foreground/25 underline-offset-[3px] transition-colors hover:decoration-foreground/70"
                        >
                            {children}
                        </button>
                    );
                }
                return (
                    <a href={href} target="_blank" rel="noopener noreferrer" className="text-foreground underline decoration-foreground/30 underline-offset-[3px] transition-colors hover:decoration-foreground/70">
                        {children}
                    </a>
                );
            },
        };
    }, [members, channels, onChannel]);

    return (
        <div className={cn('max-w-[100ch] break-words text-[15px] leading-[1.6] [&>*+*]:mt-2', muted ? 'text-muted-foreground' : 'text-foreground/90')}>
            <ReactMarkdown remarkPlugins={plugins} urlTransform={keepRefs} components={components}>
                {text}
            </ReactMarkdown>
        </div>
    );
}
