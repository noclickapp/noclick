// A message's words as markdown: bold, italic, strike, code, quotes, lists and
// links, with each @mention of a member drawn as one (an agent's in its colour, a
// person's in the accent, yours the strongest) and #channels opening the channel.
// Mentions resolve as the platform resolves them (by name, ignoring case; a name
// two members share resolves to neither) and are found in the text nodes only, so
// a `@name` inside code stays code.
import { useMemo } from 'react';
import ReactMarkdown, { defaultUrlTransform, type Components, type Options } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { SKIP, visit } from 'unist-util-visit';
import type { PhrasingContent, Root } from 'mdast';
import { cn } from '~/lib/utils';
import { MENTION_HUE, MENTION_TINT } from './avatars';
import { mentionable, mentionsIn, YOU_ID } from './model';
import type { ChannelMember } from './types';

const MENTION = 'nc-mention:';
const CHANNEL = 'nc-channel:';

interface RefOptions {
    /** The members a mention can name, by their names in lower case. */
    members: ReadonlyMap<string, ChannelMember>;
    /** The workspace's channels by name. */
    channels: ReadonlyMap<string, string>;
}

/** Turns `@Name` and `#channel` in text into links the renderer draws as mentions, a mention naming its member by id. */
function remarkChannelRefs({ members, channels }: RefOptions) {
    return (tree: Root) => {
        visit(tree, 'text', (node, index, parent) => {
            if (!parent || index === undefined || parent.type === 'link' || parent.type === 'linkReference') return;
            const text = node.value;
            const refs = [
                ...mentionsIn(text, members).map((m) => ({ ...m, url: `${MENTION}${encodeURIComponent(m.member.id)}` })),
                ...[...text.matchAll(/#[a-z0-9][a-z0-9-]*/g)].flatMap((hit) => (channels.has(hit[0].slice(1)) ? [{ start: hit.index, end: hit.index + hit[0].length, url: `${CHANNEL}${hit[0].slice(1)}` }] : [])),
            ].sort((a, b) => a.start - b.start);
            if (!refs.length) return;
            const nodes: PhrasingContent[] = [];
            let at = 0;
            for (const ref of refs) {
                if (ref.start < at) continue;
                if (ref.start > at) nodes.push({ type: 'text', value: text.slice(at, ref.start) });
                nodes.push({ type: 'link', url: ref.url, children: [{ type: 'text', value: text.slice(ref.start, ref.end) }] });
                at = ref.end;
            }
            if (at < text.length) nodes.push({ type: 'text', value: text.slice(at) });
            (parent.children as PhrasingContent[]).splice(index, 1, ...nodes);
            return [SKIP, index + nodes.length];
        });
    };
}

const PILL = 'rounded-[5px] px-1 py-px font-medium';

/** How a mention of `member` reads: an agent's in its colour on its tint, a person's in the accent, yours strongest. */
export function mentionClass(member: ChannelMember): string {
    if (member.id === YOU_ID) return cn(PILL, 'bg-foreground/[0.12] text-foreground');
    if (member.kind === 'agent' && member.hue) return cn(PILL, MENTION_HUE[member.hue], MENTION_TINT[member.hue]);
    return cn(PILL, 'bg-accent text-foreground');
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
    const plugins = useMemo((): Options['remarkPlugins'] => [remarkGfm, [remarkChannelRefs, { members: mentionable(members), channels }]], [members, channels]);
    const components = useMemo((): Components => {
        const byId = new Map(members.map((m) => [m.id, m]));
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
            // A table keeps its columns: one too wide for the message scrolls inside its own box, never the thread.
            table: ({ children }) => (
                <div className="max-w-full overflow-x-auto rounded-xl ring-1 ring-inset ring-foreground/[0.07] scrollbar-subtle">
                    <table className="min-w-full border-collapse text-[13px] leading-snug [overflow-wrap:normal]">{children}</table>
                </div>
            ),
            th: ({ children }) => <th className="border-b border-foreground/[0.08] px-3 py-1.5 text-left font-medium text-foreground">{children}</th>,
            td: ({ children }) => <td className="border-t border-foreground/[0.06] px-3 py-1.5 align-top">{children}</td>,
            hr: () => <hr className="border-border dark:border-foreground/[0.1]" />,
            a: ({ href = '', children }) => {
                if (href.startsWith(MENTION)) {
                    const member = byId.get(decodeURIComponent(href.slice(MENTION.length)));
                    return member ? (
                        <span className={mentionClass(member)} data-mention={member.kind}>
                            {children}
                        </span>
                    ) : (
                        <>{children}</>
                    );
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
        // Long unbroken text (a URL, a token) wraps anywhere rather than widening whatever lays the message out.
        <div className={cn('min-w-0 max-w-[100ch] text-[15px] leading-[1.6] [overflow-wrap:anywhere] [&>*+*]:mt-2', muted ? 'text-muted-foreground' : 'text-foreground/90')}>
            <ReactMarkdown remarkPlugins={plugins} urlTransform={keepRefs} components={components}>
                {text}
            </ReactMarkdown>
        </div>
    );
}
