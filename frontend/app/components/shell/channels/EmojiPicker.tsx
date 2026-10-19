// The composer's emoji picker: a search box (the popover focuses it on open),
// the curated sections, and the name of whatever is under the pointer, so
// `:tada:` is learnable.
import { useState } from 'react';
import { EMOJI_SECTIONS, searchEmoji, type Emoji } from './emoji';

export function EmojiPicker({ onPick }: { onPick: (emoji: Emoji) => void }) {
    const [query, setQuery] = useState('');
    const [pointed, setPointed] = useState<Emoji | null>(null);
    const results = query.trim() ? searchEmoji(query) : null;
    const sections = results ? [{ title: 'Results', items: results }] : EMOJI_SECTIONS;
    const shown = pointed ?? sections[0]?.items[0];
    return (
        <div className="flex w-[332px] max-w-[calc(100vw-24px)] flex-col" data-testid="emoji-picker">
            <div className="p-2 pb-1">
                <input
                    value={query}
                    onChange={(e) => {
                        setQuery(e.target.value);
                        setPointed(null);
                    }}
                    onKeyDown={(e) => {
                        if (e.key === 'Enter' && results?.[0]) {
                            e.preventDefault();
                            onPick(results[0]);
                        }
                    }}
                    placeholder="Search emoji"
                    aria-label="Search emoji"
                    className="h-9 w-full rounded-lg bg-foreground/[0.05] px-3 text-[14px] text-foreground outline-none ring-1 ring-inset ring-transparent transition-shadow placeholder:text-[hsl(var(--placeholder))] focus:ring-foreground/15"
                />
            </div>
            <div className="h-[252px] overflow-y-auto px-2 pb-2 scrollbar-subtle">
                {sections.map((section) => (
                    <section key={section.title}>
                        <p className="sticky top-0 z-10 bg-popover px-1 pb-1 pt-2 text-[12px] font-medium text-muted-foreground">{section.title}</p>
                        <div className="grid grid-cols-8">
                            {section.items.map((emoji) => (
                                <button
                                    key={emoji.name}
                                    type="button"
                                    onClick={() => onPick(emoji)}
                                    onMouseEnter={() => setPointed(emoji)}
                                    onFocus={() => setPointed(emoji)}
                                    aria-label={emoji.name.replace(/_/g, ' ')}
                                    className="grid aspect-square place-items-center rounded-lg text-[22px] leading-none transition-colors hover:bg-foreground/[0.07] focus-visible:bg-foreground/[0.07] focus-visible:outline-none"
                                >
                                    {emoji.char}
                                </button>
                            ))}
                        </div>
                    </section>
                ))}
                {results && !results.length && <p className="px-1 py-10 text-center text-[13px] text-muted-foreground">No emoji for “{query.trim()}”</p>}
            </div>
            <div className="flex h-11 items-center gap-2.5 border-t border-border px-3 dark:border-foreground/[0.08]">
                {shown && (
                    <>
                        <span className="text-[22px] leading-none">{shown.char}</span>
                        <span className="truncate font-mono text-[12.5px] text-muted-foreground">:{shown.name}:</span>
                    </>
                )}
            </div>
        </div>
    );
}
