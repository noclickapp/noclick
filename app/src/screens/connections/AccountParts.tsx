// An account's page, in parts: its name (renamed in place), who else may use it, in words, and where an agent's move
// brought it from, with the way to take its access away.
import { useEffect, useRef, useState } from 'react';
import { Trash2 } from 'lucide-react';
import { movedDate, type MovedFrom } from '@/lib/movedFrom';
import { Section, Surface } from '@/screens/resources/ui';
import { BUTTON_SECONDARY } from '@/ui/buttons';
import { PAGE_TITLE } from '@/ui/titles';
import { cn } from '@/ui/utils';

/** Someone or a workspace an account is shared with. */
export interface Share {
    /** `organization` for a workspace, else a person. */
    target_type: string;
    target_org_name?: string | null;
    target_display_name?: string | null;
    target_email?: string | null;
}

/** Who else may use an account, in a sentence. */
export function sharingLine(shares: readonly Share[]): string {
    if (!shares.length) return 'Only you can use it.';
    const names = shares.map((s) =>
        s.target_type === 'organization' ? `everyone in ${s.target_org_name || 'your organization'}` : s.target_display_name || s.target_email || 'someone'
    );
    const listed = names.length > 3 ? [...names.slice(0, 2), `${names.length - 2} others`] : names;
    return `Shared with ${new Intl.ListFormat('en', { type: 'conjunction' }).format(listed)}.`;
}

/** Where an agent's move brought it from, and the way to take its access away (its owner's alone). */
export function Moved({ moved, owner, onRemove }: { moved: MovedFrom; owner: boolean; onRemove: () => void }) {
    const where = [moved.host ?? 'a computer', moved.folder ? `in ${moved.folder}` : null].filter(Boolean).join(', ');
    return (
        <Section title="Moved here">
            <Surface className="flex flex-wrap items-center gap-x-4 gap-y-3 px-4 py-3.5 sm:px-5">
                <div className="min-w-0 flex-1" data-testid="account-moved">
                    <p className="text-[14px] leading-snug text-foreground/90">
                        It came over from {where}
                        {moved.at ? ` on ${movedDate(moved.at)}` : ''}, when an agent moved here.
                    </p>
                    <p className="mt-0.5 text-[13.5px] text-muted-foreground">Removing it takes its access away from every agent and automation that uses it.</p>
                </div>
                {owner && (
                    <button type="button" onClick={onRemove} className={cn(BUTTON_SECONDARY, 'hover:text-red-600 dark:hover:text-red-400')}>
                        <Trash2 className="h-4 w-4" />
                        Remove
                    </button>
                )}
            </Surface>
        </Section>
    );
}

/** The account's name as its page's title, an input while `renaming`: Enter or leaving it saves (once), Escape
 *  doesn't. The new name shows until the account comes back renamed; `onRename` answers whether it took. */
export function AccountTitle({ name, renaming, onRename, onDone }: { name: string; renaming: boolean; onRename: (next: string) => Promise<boolean>; onDone: () => void }) {
    const input = useRef<HTMLInputElement>(null);
    const [draft, setDraft] = useState(name);
    // Shown until the renamed account comes back from the list.
    const [pending, setPending] = useState<string | null>(null);
    const settled = useRef(false);
    useEffect(() => setPending(null), [name]);
    useEffect(() => {
        if (!renaming) return;
        settled.current = false;
        setDraft(name);
        requestAnimationFrame(() => {
            input.current?.focus();
            input.current?.select();
        });
    }, [renaming, name]);
    const title = cn('min-w-0', PAGE_TITLE);
    if (!renaming) return <h1 className={cn(title, 'break-words sm:truncate')}>{pending ?? name}</h1>;
    // Enter and the blur that follows it must save once.
    const finish = (save: boolean) => {
        if (settled.current) return;
        settled.current = true;
        const next = draft.trim();
        onDone();
        if (!save || !next || next === name) return;
        setPending(next);
        void onRename(next).then((ok) => !ok && setPending(null));
    };
    return (
        <input
            ref={input}
            value={draft}
            aria-label="Account name"
            onChange={(e) => setDraft(e.target.value)}
            onBlur={() => finish(true)}
            onKeyDown={(e) => {
                if (e.key === 'Enter') finish(true);
                if (e.key === 'Escape') finish(false);
            }}
            className={cn(title, '-mx-2 w-full rounded-lg bg-transparent px-2 outline-none ring-1 ring-inset ring-border focus:ring-foreground/30 sm:w-[min(100%,28rem)]')}
        />
    );
}
