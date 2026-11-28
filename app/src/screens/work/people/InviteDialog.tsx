// Inviting people to a space: one link to share first (anyone signed in to NoClick who opens it joins, as a member or
// a guest), or an invite sent to one email address. Joining adds them as your account's users: what they do in the
// space is paid by its owner, up to the plan's people. Your personal space takes people the same way, never showing
// them your chat with NoClick, your DMs or your settings.
import { useState, type FormEvent } from 'react';
import { Link2, UserPlus } from 'lucide-react';
import { toast } from 'sonner';
import { HAIRLINE } from '@/ui/primitives';
import { BUTTON_GHOST, BUTTON_PRIMARY, BUTTON_SECONDARY } from '@/ui/buttons';
import { FIELD_LABEL } from '@/ui/fields';
import { ShellDialog } from '@/ui/ShellDialog';
import type { WorkspaceRole } from 'noclick';
import { cn } from '@/ui/utils';
import { spaceWhere, type WorkSpace } from '../spaces';
import type { SpacePeople } from './members';

const SMALL_PRIMARY = BUTTON_PRIMARY.replace('h-9', 'h-8');
const SMALL_GHOST = BUTTON_GHOST.replace('h-9', 'h-8');
const CHOICES: [Exclude<WorkspaceRole, 'admin'>, string][] = [
    ['member', 'Every agent and channel here, and what the space is connected to'],
    ['guest', 'Only the channels you add them to, and those channels’ agents'],
];
const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export function InviteDialog({ open, onOpenChange, space, people }: { open: boolean; onOpenChange: (open: boolean) => void; space: WorkSpace; people: SpacePeople }) {
    const link = people.invites.find((i) => i.type === 'link' && i.status === 'active') ?? null;
    const [role, setRole] = useState<Exclude<WorkspaceRole, 'admin'>>(link?.role === 'guest' ? 'guest' : 'member');
    const [email, setEmail] = useState('');
    const [busy, setBusy] = useState<'link' | 'email' | null>(null);
    const [problem, setProblem] = useState<string | null>(null);
    const full = people.peopleLimit !== null && people.peopleCount >= people.peopleLimit;
    const where = spaceWhere(space);
    const yours = space.own && !!space.personal;
    const Where = where.charAt(0).toUpperCase() + where.slice(1);

    const run = async (what: 'link' | 'email', work: () => Promise<void>) => {
        setBusy(what);
        setProblem(null);
        try {
            await work();
        } catch (e) {
            setProblem(e instanceof Error ? e.message : 'Something went wrong.');
        } finally {
            setBusy(null);
        }
    };
    const copy = (url: string) =>
        navigator.clipboard.writeText(url).then(
            () => toast('Invite link copied', { description: `Anyone signed in to NoClick who opens it joins ${where} as a ${role}.` }),
            () => toast.error('Couldn’t copy the link')
        );
    const makeLink = () =>
        run('link', async () => {
            const made = await people.newLink(role);
            if (made.url) await copy(made.url);
        });
    const send = (e: FormEvent) => {
        e.preventDefault();
        const to = email.trim();
        if (!EMAIL.test(to)) return setProblem('That doesn’t look like an email address.');
        void run('email', async () => {
            await people.invite(to, role);
            setEmail('');
            toast('Invite sent', { description: `${to} gets an email with a link to join ${where}.` });
        });
    };
    const pickRole = (next: Exclude<WorkspaceRole, 'admin'>) => {
        setRole(next);
        // The link joins people as one role: a new one for the other.
        if (link && link.role !== next) void run('link', async () => void (await people.newLink(next)));
    };

    return (
        <ShellDialog
            open={open}
            onOpenChange={onOpenChange}
            size="md"
            title={`Invite people to ${where}`}
            description={`They can message the agents here and use what the space is connected to.${yours ? ' Your chat with NoClick, your DMs and your settings stay yours.' : ''}`}
            mark={<UserPlus className="h-5 w-5" strokeWidth={1.75} />}
            testId="invite-dialog"
            footer={
                <>
                    {people.peopleLimit !== null && (
                        <span className="mr-auto text-[12.5px] tabular-nums text-muted-foreground">
                            {people.peopleCount} of {people.peopleLimit} people in {where}
                        </span>
                    )}
                    <button type="button" onClick={() => onOpenChange(false)} className={BUTTON_PRIMARY}>
                        Done
                    </button>
                </>
            }
        >
            <div className="space-y-6 pb-1 pt-1">
                {full && (
                    <p role="alert" className="text-[13px] leading-snug text-muted-foreground">
                        {Where} has as many people as its plan allows ({people.peopleLimit}). Remove someone, or move to Member for up to 50.
                    </p>
                )}
                <div>
                    <span className={FIELD_LABEL}>Invite link</span>
                    {link?.url ? (
                        <>
                            <div className={cn('flex items-center gap-2 rounded-full border py-1.5 pl-3.5 pr-1.5', HAIRLINE)}>
                                <span className="min-w-0 flex-1 truncate text-[14px] text-foreground/85" data-testid="invite-link">
                                    {link.url.replace(/^https?:\/\//, '')}
                                </span>
                                <button type="button" onClick={() => void copy(link.url!)} className={SMALL_PRIMARY}>
                                    <Link2 className="h-4 w-4" strokeWidth={1.9} />
                                    Copy
                                </button>
                            </div>
                            <p className="mt-1.5 flex flex-wrap items-center gap-x-1 text-[12.5px] text-muted-foreground">
                                {link.expiresAt ? `Works until ${link.expiresAt.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}` : 'Works until you turn it off'}
                                {link.usesLeft !== null ? `, for ${link.usesLeft} more ${link.usesLeft === 1 ? 'person' : 'people'}.` : '.'}
                                <button type="button" disabled={!!busy} onClick={() => void run('link', () => people.revoke(link))} className={cn(SMALL_GHOST, 'h-7 px-2 text-[12.5px]')}>
                                    Turn it off
                                </button>
                            </p>
                        </>
                    ) : (
                        <button type="button" disabled={!!busy || full} onClick={() => void makeLink()} className={cn(BUTTON_SECONDARY, 'w-full justify-center')}>
                            <Link2 className="h-4 w-4" strokeWidth={1.9} />
                            {busy === 'link' ? 'Making a link…' : 'Make a link to share'}
                        </button>
                    )}
                </div>
                <div>
                    <span className={FIELD_LABEL}>{link ? 'Anyone with the link joins as' : 'People you invite join as'}</span>
                    <div className="grid grid-cols-2 gap-2">
                        {CHOICES.map(([r, note]) => (
                            <button
                                key={r}
                                type="button"
                                onClick={() => pickRole(r)}
                                aria-pressed={role === r}
                                className={cn('rounded-2xl border p-3 text-left transition-colors', role === r ? 'border-foreground/50 bg-foreground/[0.04]' : cn(HAIRLINE, 'hover:bg-foreground/[0.03]'))}
                            >
                                <span className="flex items-center gap-2 text-[14px] font-medium capitalize">
                                    <span className={cn('grid h-4 w-4 place-items-center rounded-full ring-1 ring-inset', role === r ? 'ring-foreground' : 'ring-foreground/30')}>
                                        {role === r && <span className="h-2 w-2 rounded-full bg-foreground" />}
                                    </span>
                                    {r}
                                </span>
                                <span className="mt-1 block text-[12.5px] leading-snug text-muted-foreground">{note}</span>
                            </button>
                        ))}
                    </div>
                </div>
                <form onSubmit={send}>
                    <span className={FIELD_LABEL}>Or send it</span>
                    <div className="flex gap-2">
                        <input
                            type="email"
                            value={email}
                            onChange={(e) => {
                                setEmail(e.target.value);
                                setProblem(null);
                            }}
                            placeholder="Email address"
                            aria-label="Email address"
                            className={cn('h-10 min-w-0 flex-1 rounded-full border bg-transparent px-4 text-[14.5px] outline-none placeholder:text-[hsl(var(--placeholder))] focus:border-foreground/30', HAIRLINE)}
                        />
                        <button type="submit" disabled={!email.trim() || !!busy || full} className={BUTTON_SECONDARY.replace('h-9', 'h-10')}>
                            {busy === 'email' ? 'Sending…' : 'Send'}
                        </button>
                    </div>
                </form>
                {problem && (
                    <p role="alert" className="text-[13px] text-red-600 dark:text-red-400">
                        {problem}
                    </p>
                )}
            </div>
        </ShellDialog>
    );
}
