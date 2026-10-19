// A channel's composer, with Slack's reach and NoClick's restraint: markdown
// formatting from a bar or the keyboard, files from the picker, a paste or a
// drop, emoji, @-mentions of the channel's people and agents, voice clips, and
// slash commands. Enter sends; Shift+Enter starts a new line (and carries a
// list on). The draft and its files belong to the page, one per channel; a
// file uploads as it's attached, and Send waits for it (one that failed holds
// Send until it's removed).
import { useRef, useState, useSyncExternalStore, type ReactNode, type RefObject } from 'react';
import {
    AtSign,
    Bold,
    Check,
    Code,
    Italic,
    Link2,
    List,
    ListOrdered,
    Mic,
    Plus,
    Smile,
    SquareCode,
    SquareSlash,
    Strikethrough,
    TextQuote,
    X,
    type LucideIcon,
} from 'lucide-react';
import { toast } from 'sonner';
import { AttachmentTrayItem, COMPOSER_SURFACE, ComposerSendButton } from '~/components/chat/AgentChatComposer';
import type { AccountMenuUser } from '~/components/nav/AccountMenu';
import { NodeMark } from '~/components/dashboard/primitives';
import { Popover, PopoverAnchor, PopoverContent, PopoverTrigger } from '~/components/ui/popover';
import { Tooltip, TooltipContent, TooltipTrigger } from '~/components/ui/tooltip';
import { useAutoGrowTextarea } from '~/hooks/useAutoGrowTextarea';
import { useSurfaceFocus } from '~/hooks/useSurfaceFocus';
import { useComposerAutocomplete, type AutocompleteMatch, type AutocompleteSource } from '~/hooks/useComposerAutocomplete';
import type { PendingChatAttachment } from '~/hooks/useChatAttachments';
import { useIsMobile } from '~/hooks/useIsMobile';
import { useModKey } from '~/hooks/useIsMac';
import { useTextFormatting } from '~/hooks/useTextFormatting';
import { useVoiceClip, type VoiceClip } from '~/hooks/useVoiceClip';
import { cn } from '~/lib/utils';
import type { TextFormat } from '~/utils/markdownFormat';
import { clipClock, VoicePlayer } from './attachments';
import { MemberAvatar } from './avatars';
import { CHANNEL_COMMANDS, type ChannelCommand } from './commands';
import { searchEmoji, type Emoji } from './emoji';
import { EmojiPicker } from './EmojiPicker';
import type { ChannelAttachment, ChannelMember } from './types';

/** A file waiting in the composer: the tray's shape, plus what the message will carry once it's uploaded. */
export interface DraftAttachment extends PendingChatAttachment {
    kind: ChannelAttachment['kind'];
    /** The local copy, shown and played until the message lands. */
    url: string;
    voice?: boolean;
    durationMs?: number;
    peaks?: number[];
    /** Set once uploaded: what the message carries. */
    attachment?: ChannelAttachment;
}

type Suggestion = { kind: 'member'; member: ChannelMember } | { kind: 'command'; command: ChannelCommand } | { kind: 'emoji'; emoji: Emoji };

const FORMATS: { format: TextFormat; label: string; icon: LucideIcon; keys?: string }[][] = [
    [
        { format: 'bold', label: 'Bold', icon: Bold, keys: 'B' },
        { format: 'italic', label: 'Italic', icon: Italic, keys: 'I' },
        { format: 'strike', label: 'Strikethrough', icon: Strikethrough, keys: '⇧X' },
    ],
    [{ format: 'link', label: 'Link', icon: Link2, keys: '⇧U' }],
    [
        { format: 'numbered', label: 'Numbered list', icon: ListOrdered, keys: '⇧7' },
        { format: 'bulleted', label: 'Bulleted list', icon: List, keys: '⇧8' },
    ],
    [{ format: 'quote', label: 'Quote', icon: TextQuote, keys: '⇧9' }],
    [
        { format: 'code', label: 'Code', icon: Code, keys: 'E' },
        { format: 'codeBlock', label: 'Code block', icon: SquareCode },
    ],
];

// The formatting bar stays open or shut on this device, as Slack's does.
const FORMAT_BAR_KEY = 'nc-channel-format-bar';
let formatBarOpen: boolean | null = null;
const formatBarListeners = new Set<() => void>();

function formatBarSnapshot(): boolean {
    if (formatBarOpen === null) {
        try {
            formatBarOpen = window.localStorage.getItem(FORMAT_BAR_KEY) === '1';
        } catch {
            formatBarOpen = false;
        }
    }
    return formatBarOpen;
}

function setFormatBarOpen(open: boolean) {
    formatBarOpen = open;
    try {
        window.localStorage.setItem(FORMAT_BAR_KEY, open ? '1' : '0');
    } catch {
        // Not remembered this time; the bar still toggles.
    }
    formatBarListeners.forEach((listener) => listener());
}

function subscribeFormatBar(listener: () => void) {
    formatBarListeners.add(listener);
    return () => {
        formatBarListeners.delete(listener);
    };
}

const ICON_BUTTON =
    'grid h-8 w-8 shrink-0 place-items-center rounded-full text-muted-foreground transition-colors hover:bg-foreground/[0.07] hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-40';

function Tip({ label, keys, children }: { label: string; keys?: string; children: ReactNode }) {
    return (
        <Tooltip>
            <TooltipTrigger asChild>{children}</TooltipTrigger>
            <TooltipContent side="top" sideOffset={8} className="rounded-lg px-2 py-1 text-[12.5px]">
                {label}
                {keys && <span className="ml-2 text-muted-foreground">{keys}</span>}
            </TooltipContent>
        </Tooltip>
    );
}

function Divider() {
    return <span aria-hidden className="mx-1 h-5 w-px shrink-0 bg-border dark:bg-foreground/[0.1]" />;
}

function SuggestionRow({ item, user, active }: { item: Suggestion; user: AccountMenuUser; active: boolean }) {
    if (item.kind === 'member') {
        const { member } = item;
        return (
            <>
                <MemberAvatar member={member} user={user} size={24} />
                <span className="min-w-0 flex-1 truncate">
                    <span className="text-[14px] font-medium text-foreground">{member.name}</span>
                    {member.kind === 'outside' && <span className="ml-2 text-[12.5px] text-muted-foreground">outside agent</span>}
                </span>
                {member.markType && <NodeMark type={member.markType} size="xs" />}
            </>
        );
    }
    if (item.kind === 'command') {
        const { command } = item;
        const Icon = command.icon;
        return (
            <>
                <span className="grid h-7 w-7 shrink-0 place-items-center rounded-lg bg-foreground/[0.06]">
                    <Icon className="h-[15px] w-[15px] text-foreground/75" strokeWidth={1.75} />
                </span>
                <span className="min-w-0 flex-1 truncate">
                    <span className="text-[14px] font-medium text-foreground">/{command.name}</span>
                    <span className="ml-2 text-[12.5px] text-muted-foreground">{command.description}</span>
                </span>
                {active && command.args && <span className="hidden shrink-0 text-[12px] text-muted-foreground/80 sm:inline">{command.args}</span>}
            </>
        );
    }
    return (
        <>
            <span className="w-7 shrink-0 text-center text-[20px] leading-none">{item.emoji.char}</span>
            <span className="truncate font-mono text-[13px] text-foreground/85">:{item.emoji.name}:</span>
        </>
    );
}

function SuggestionMenu({
    match,
    active,
    user,
    onPick,
    onPoint,
}: {
    match: AutocompleteMatch<Suggestion>;
    active: number;
    user: AccountMenuUser;
    onPick: (index: number) => void;
    onPoint: (index: number) => void;
}) {
    const title = match.source.trigger === '@' ? 'People and agents' : match.source.trigger === '/' ? 'Commands' : `Emoji matching :${match.query}`;
    return (
        <div
            role="listbox"
            aria-label={title}
            data-testid="composer-suggestions"
            className="absolute inset-x-0 bottom-full z-50 mb-2 overflow-hidden rounded-2xl border border-border bg-popover p-1.5 shadow-xl dark:border-foreground/[0.1] sm:right-auto sm:w-[420px]"
        >
            <p className="px-2.5 pb-1 pt-1 text-[12px] font-medium text-muted-foreground">{title}</p>
            {match.items.map((item, i) => (
                <button
                    key={item.kind === 'member' ? item.member.id : item.kind === 'command' ? item.command.name : item.emoji.name}
                    type="button"
                    role="option"
                    aria-selected={i === active}
                    // Keep the caret in the textarea: a mousedown here must not blur it before the pick.
                    onMouseDown={(e) => e.preventDefault()}
                    onClick={() => onPick(i)}
                    onMouseEnter={() => onPoint(i)}
                    className={cn('flex h-10 w-full items-center gap-3 rounded-xl px-2.5 text-left', i === active && 'bg-accent')}
                >
                    <SuggestionRow item={item} user={user} active={i === active} />
                </button>
            ))}
            <p className="mt-1 hidden gap-3 border-t border-border px-2.5 pb-0.5 pt-2 text-[11.5px] text-muted-foreground dark:border-foreground/[0.08] md:flex">
                <span>↑↓ to move</span>
                <span>↵ to pick</span>
                <span>esc to close</span>
            </p>
        </div>
    );
}

/** Loudness while recording, newest at the right. */
function LiveMeter({ levels }: { levels: number[] }) {
    return (
        <div aria-hidden className="flex h-8 min-w-0 flex-1 items-center justify-end gap-[2px] overflow-hidden">
            {levels.map((level, i) => (
                <span key={i} className="w-[3px] shrink-0 rounded-full bg-foreground/70" style={{ height: `${Math.round(3 + level * 22)}px` }} />
            ))}
        </div>
    );
}

export function ChannelComposer({
    channelName,
    value,
    onChange,
    attachments,
    onAddFiles,
    onAddClip,
    onRemoveAttachment,
    onSubmit,
    members,
    user,
    textareaRef,
    disabled,
}: {
    channelName: string;
    value: string;
    onChange: (value: string) => void;
    attachments: DraftAttachment[];
    onAddFiles: (files: File[]) => void;
    onAddClip: (clip: VoiceClip) => void;
    onRemoveAttachment: (localId: string) => void;
    onSubmit: () => void;
    /** Who can be @-mentioned: the channel's people and agents, you aside. */
    members: ChannelMember[];
    user: AccountMenuUser;
    textareaRef: RefObject<HTMLTextAreaElement | null>;
    /** Why nothing can be posted (a closed channel), shown in place of the box. */
    disabled?: string;
}) {
    const isMobile = useIsMobile();
    const mod = useModKey();
    const formatBar = useSyncExternalStore(subscribeFormatBar, formatBarSnapshot, () => false);
    const [emojiOpen, setEmojiOpen] = useState(false);
    const fileInput = useRef<HTMLInputElement>(null);
    const voice = useVoiceClip({ onError: (message) => toast.error(message) });
    const recording = voice.state !== 'idle';
    useAutoGrowTextarea(textareaRef, value, isMobile ? 132 : 240);
    const focusText = useSurfaceFocus(textareaRef);

    const sources: AutocompleteSource<Suggestion>[] = [
        {
            trigger: '@',
            search: (query) => {
                const q = query.toLowerCase();
                return members.filter((m) => m.name.toLowerCase().startsWith(q)).map((member): Suggestion => ({ kind: 'member', member }));
            },
            insert: (item) => (item.kind === 'member' ? `@${item.member.name}` : ''),
        },
        {
            trigger: '/',
            atStart: true,
            search: (query) => CHANNEL_COMMANDS.filter((c) => c.name.startsWith(query.toLowerCase())).map((command): Suggestion => ({ kind: 'command', command })),
            insert: (item) => (item.kind === 'command' ? `/${item.command.name}` : ''),
        },
        {
            trigger: ':',
            minQuery: 2,
            search: (query) => searchEmoji(query).map((emoji): Suggestion => ({ kind: 'emoji', emoji })),
            insert: (item) => (item.kind === 'emoji' ? item.emoji.char : ''),
        },
    ];
    const autocomplete = useComposerAutocomplete({ sources, textareaRef, onChange });
    const format = useTextFormatting(textareaRef, onChange, autocomplete.sync);
    const uploading = attachments.some((a) => a.status !== 'ready');
    const canSend = !recording && !uploading && (!!value.trim() || attachments.length > 0);

    const toggleFormatBar = () => {
        setFormatBarOpen(!formatBar);
        textareaRef.current?.focus();
    };

    /** `@` at the caret (after a space if it would join a word), opening the mentions. */
    const typeMention = () => {
        const el = textareaRef.current;
        const before = el ? el.value.slice(0, el.selectionStart) : '';
        format.insert(before && !/\s$/.test(before) ? ' @' : '@');
    };

    /** Commands only count at the start of a message: open them there, the draft becoming what follows. */
    const openCommands = () => {
        const word = /^\/\S*/.exec(value)?.[0];
        if (word) format.commit({ value, selectionStart: word.length, selectionEnd: word.length });
        else format.commit({ value: value ? `/ ${value}` : '/', selectionStart: 1, selectionEnd: 1 });
    };

    const finishClip = async () => {
        const clip = await voice.stop();
        if (clip) onAddClip(clip);
        textareaRef.current?.focus();
    };

    if (disabled) {
        return (
            <div className="shrink-0 px-3 pb-4 pt-2 sm:px-5 sm:pb-5">
                <p className={cn('rounded-[20px] px-4 py-4 text-center text-[14px] text-muted-foreground', COMPOSER_SURFACE)} data-testid="channel-composer-disabled">
                    {disabled}
                </p>
            </div>
        );
    }

    return (
        <div className="shrink-0 px-3 pb-4 pt-2 sm:px-5 sm:pb-5">
            <Popover open={emojiOpen} onOpenChange={setEmojiOpen}>
                <div className="w-full">
                    {/* The emoji picker opens above the whole box, clear of the text. */}
                    <PopoverAnchor asChild>
                        {/* Pointer convenience only: keyboard users reach the text by Tab. */}
                        {/* eslint-disable-next-line jsx-a11y/no-static-element-interactions */}
                        <div className={cn('relative z-10 cursor-text rounded-[20px]', COMPOSER_SURFACE)} data-testid="channel-composer" onMouseDown={focusText}>
                            {autocomplete.match && (
                                <SuggestionMenu match={autocomplete.match} active={autocomplete.active} user={user} onPick={autocomplete.accept} onPoint={autocomplete.setActive} />
                            )}
                            {formatBar && (
                                <div role="toolbar" aria-label="Formatting" className="flex items-center gap-0.5 overflow-x-auto px-2.5 pt-2 scrollbar-hide" data-testid="format-bar">
                                    {FORMATS.map((group, g) => (
                                        <div key={g} className="flex items-center gap-0.5">
                                            {g > 0 && <Divider />}
                                            {group.map(({ format: f, label, icon: Icon, keys }) => (
                                                <Tip key={f} label={label} keys={keys && `${mod}${keys}`}>
                                                    <button
                                                        type="button"
                                                        aria-label={label}
                                                        // The selection stays in the textarea while the button formats it.
                                                        onMouseDown={(e) => e.preventDefault()}
                                                        onClick={() => format.apply(f)}
                                                        className="grid h-8 w-8 shrink-0 place-items-center rounded-lg text-muted-foreground transition-colors hover:bg-foreground/[0.07] hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                                                    >
                                                        <Icon className="h-4 w-4" strokeWidth={1.9} />
                                                    </button>
                                                </Tip>
                                            ))}
                                        </div>
                                    ))}
                                </div>
                            )}
                            {attachments.length > 0 && (
                                <div className="flex flex-wrap items-center gap-2 px-3.5 pt-3.5" data-testid="channel-attachment-tray">
                                    {attachments.map((a) =>
                                        a.voice && a.durationMs !== undefined ? (
                                            <div key={a.localId} className="group relative" title={a.status === 'error' ? a.error : undefined} data-status={a.status}>
                                                <VoicePlayer
                                                    url={a.url}
                                                    durationMs={a.durationMs}
                                                    peaks={a.peaks ?? []}
                                                    className={cn('py-1 pl-1 pr-3', a.status === 'uploading' && 'opacity-60', a.status === 'error' && 'ring-red-500/60')}
                                                />
                                                <button
                                                    type="button"
                                                    onClick={() => onRemoveAttachment(a.localId)}
                                                    aria-label="Remove voice clip"
                                                    className="absolute -right-1.5 -top-1.5 flex h-[18px] w-[18px] items-center justify-center rounded-full border border-border bg-popover text-muted-foreground opacity-0 shadow-sm transition-opacity hover:text-foreground focus-visible:opacity-100 group-hover:opacity-100 [@media(hover:none)]:opacity-100"
                                                >
                                                    <X className="h-3 w-3" strokeWidth={2.5} />
                                                </button>
                                            </div>
                                        ) : (
                                            <AttachmentTrayItem key={a.localId} attachment={a} onRemove={onRemoveAttachment} />
                                        )
                                    )}
                                </div>
                            )}
                            <textarea
                                ref={textareaRef}
                                value={value}
                                rows={1}
                                placeholder={`Message #${channelName}`}
                                aria-label={`Message #${channelName}`}
                                onChange={(e) => {
                                    onChange(e.target.value);
                                    autocomplete.sync(e.target);
                                }}
                                onKeyDown={(e) => {
                                    // The suggestions' keys come first: Enter picks before it sends.
                                    if (autocomplete.onKeyDown(e) || format.onKeyDown(e)) return;
                                    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
                                        e.preventDefault();
                                        if (canSend) onSubmit();
                                    }
                                }}
                                onKeyUp={(e) => {
                                    if (autocomplete.match && ['ArrowDown', 'ArrowUp', 'Enter', 'Tab', 'Escape'].includes(e.key)) return;
                                    autocomplete.sync(e.currentTarget);
                                }}
                                onClick={(e) => autocomplete.sync(e.currentTarget)}
                                onBlur={autocomplete.close}
                                onPaste={(e) => {
                                    const files = e.clipboardData?.files;
                                    if (files?.length) {
                                        e.preventDefault();
                                        onAddFiles(Array.from(files));
                                    }
                                }}
                                className="block min-h-[48px] w-full resize-none overflow-y-auto bg-transparent px-4 pb-1 pt-3 text-[15px] leading-6 text-foreground outline-none placeholder:text-[hsl(var(--placeholder))] scrollbar-subtle sm:min-h-[60px]"
                            />
                            {recording ? (
                                <div className="flex h-12 items-center gap-3 px-3 pb-2 pt-0.5" data-testid="voice-recording">
                                    <span className="relative ml-1 flex h-2.5 w-2.5 shrink-0">
                                        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-red-500/50 motion-reduce:animate-none" />
                                        <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-red-600 dark:bg-red-500" />
                                    </span>
                                    <span className="w-9 shrink-0 text-[13px] tabular-nums text-foreground">{clipClock(voice.elapsedMs)}</span>
                                    <LiveMeter levels={voice.levels} />
                                    <button
                                        type="button"
                                        onClick={voice.cancel}
                                        className="inline-flex h-8 shrink-0 items-center rounded-full px-3 text-[13px] text-muted-foreground transition-colors hover:bg-foreground/[0.06] hover:text-foreground"
                                    >
                                        Cancel
                                    </button>
                                    <button
                                        type="button"
                                        onClick={() => void finishClip()}
                                        disabled={voice.state !== 'recording'}
                                        aria-label="Done recording"
                                        className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-primary text-primary-foreground transition-opacity hover:opacity-90 disabled:opacity-40"
                                    >
                                        <Check className="h-[18px] w-[18px]" strokeWidth={2.25} />
                                    </button>
                                </div>
                            ) : (
                                <div className="flex items-center gap-0.5 px-2 pb-2 pt-1">
                                    <input
                                        ref={fileInput}
                                        type="file"
                                        multiple
                                        className="hidden"
                                        data-testid="channel-file-input"
                                        onChange={(e) => {
                                            if (e.target.files?.length) onAddFiles(Array.from(e.target.files));
                                            // The same file picked twice should fire again.
                                            e.target.value = '';
                                        }}
                                    />
                                    <Tip label="Attach files">
                                        <button
                                            type="button"
                                            onClick={() => fileInput.current?.click()}
                                            aria-label="Attach files"
                                            className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-foreground/[0.06] text-foreground/75 transition-colors hover:bg-foreground/[0.1] hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                                        >
                                            <Plus className="h-[18px] w-[18px]" strokeWidth={1.9} />
                                        </button>
                                    </Tip>
                                    <Tip label={formatBar ? 'Hide formatting' : 'Show formatting'}>
                                        <button
                                            type="button"
                                            onClick={toggleFormatBar}
                                            aria-label="Formatting"
                                            aria-pressed={formatBar}
                                            data-testid="format-toggle"
                                            className={cn(ICON_BUTTON, 'ml-1 text-[13.5px] font-semibold', formatBar && 'bg-foreground/[0.08] text-foreground')}
                                        >
                                            <span className="underline decoration-[1.5px] underline-offset-[3px]">Aa</span>
                                        </button>
                                    </Tip>
                                    <Tip label="Emoji">
                                        <PopoverTrigger aria-label="Emoji" data-testid="emoji-button" className={cn(ICON_BUTTON, emojiOpen && 'bg-foreground/[0.08] text-foreground')}>
                                            <Smile className="h-[18px] w-[18px]" strokeWidth={1.75} />
                                        </PopoverTrigger>
                                    </Tip>
                                    <Tip label="Mention someone">
                                        <button type="button" onClick={typeMention} aria-label="Mention someone" className={ICON_BUTTON}>
                                            <AtSign className="h-[18px] w-[18px]" strokeWidth={1.75} />
                                        </button>
                                    </Tip>
                                    <Divider />
                                    <Tip label="Record a voice clip">
                                        <button type="button" onClick={() => void voice.start()} aria-label="Record a voice clip" data-testid="voice-button" className={ICON_BUTTON}>
                                            <Mic className="h-[18px] w-[18px]" strokeWidth={1.75} />
                                        </button>
                                    </Tip>
                                    <Divider />
                                    <Tip label="Commands">
                                        <button type="button" onClick={openCommands} aria-label="Commands" className={ICON_BUTTON}>
                                            <SquareSlash className="h-[18px] w-[18px]" strokeWidth={1.75} />
                                        </button>
                                    </Tip>
                                    <div className="ml-auto pl-2">
                                        <ComposerSendButton onClick={onSubmit} disabled={!canSend} />
                                    </div>
                                </div>
                            )}
                        </div>
                    </PopoverAnchor>
                </div>
                <PopoverContent
                    side="top"
                    align="start"
                    sideOffset={8}
                    collisionPadding={12}
                    className="w-auto rounded-2xl p-0"
                    onCloseAutoFocus={(e) => {
                        e.preventDefault();
                        textareaRef.current?.focus();
                    }}
                >
                    <EmojiPicker
                        onPick={(emoji) => {
                            format.insert(emoji.char);
                            setEmojiOpen(false);
                        }}
                    />
                </PopoverContent>
            </Popover>
        </div>
    );
}
