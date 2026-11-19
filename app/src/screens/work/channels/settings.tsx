// A channel's settings from its ⋯ menu: renaming it and its topic (the channel's PATCH), deleting it to the trash after
// the platform's own preview of what stops with it (then Undo puts it back), and what a closed channel, or any channel
// of an archived space, shows in its box's place.
import { useEffect, useState, type FormEvent, type ReactNode } from 'react';
import { toast } from 'sonner';
import { Archive, Hash, Lock, type LucideIcon } from 'lucide-react';
import { ShellDialog } from '@/ui/ShellDialog';
import { BUTTON_GHOST, BUTTON_PRIMARY, BUTTON_SECONDARY } from '@/ui/buttons';
import { DeleteConfirmPopup } from '@/ui/DeleteConfirmPopup';
import { PILL_FIELD } from '@/ui/fields';
import { channelSlug } from '@/screens/channels/model';
import type { Channel } from '@/screens/channels/types';
import type { Channels } from '@/screens/channels/useChannels';
import { cn } from '@/ui/utils';
import { errorText } from '@/screens/console/pages/resources/shared';
import { useWorkClient } from '../client';
import { previewCall, type Impact } from '../resources/space/actions';

export type ChannelDialog = 'rename' | 'topic' | 'delete' | 'reopen';

/** Rename, Edit topic, Delete, or reopen under another name, for `channel`; `onGone` once it's in the trash. */
export function ChannelSettingsDialog({ kind, channel, channels, onClose, onGone }: { kind: ChannelDialog; channel: Channel; channels: Channels; onClose: () => void; onGone: () => void }) {
    return kind === 'delete' ? <DeleteChannel channel={channel} channels={channels} onClose={onClose} onGone={onGone} /> : <TextSetting kind={kind} channel={channel} channels={channels} onClose={onClose} />;
}

/** What each text setting asks, saves and says. */
const TEXT = {
    rename: { title: (c: Channel) => `Rename #${c.name}`, line: 'Everyone in it sees the new name. Links to it keep working.', start: (c: Channel) => c.name },
    topic: { title: (c: Channel) => `Topic of #${c.name}`, line: 'A line under its name, saying what it’s for.', start: (c: Channel) => c.topic },
    reopen: { title: (c: Channel) => `Reopen #${c.name}`, line: 'An open channel here has its name, so it reopens under another.', start: (c: Channel) => `${c.name}-2` },
};

function TextSetting({ kind, channel, channels, onClose }: { kind: 'rename' | 'topic' | 'reopen'; channel: Channel; channels: Channels; onClose: () => void }) {
    const named = kind !== 'topic';
    const [text, setText] = useState(() => TEXT[kind].start(channel));
    const [busy, setBusy] = useState(false);
    const slug = channelSlug(text);
    const unchanged = named ? !slug || slug === channel.name : text.trim() === channel.topic;
    const submit = async (e: FormEvent) => {
        e.preventDefault();
        if (unchanged || busy) return;
        setBusy(true);
        try {
            if (kind === 'reopen') await channels.reopen(channel.id, slug);
            else await channels.updateChannel(channel.id, kind === 'rename' ? { name: slug } : { topic: text.trim() });
            if (kind === 'rename') toast(`Renamed #${channel.name} to #${slug}`, { description: 'Links to it still work.' });
            else if (kind === 'reopen') toast(`Reopened #${channel.name} as #${slug}`, { description: 'Everyone can post in it again.' });
            else toast('Topic changed');
            onClose();
        } catch (error) {
            toast(kind === 'topic' ? 'Couldn’t change its topic' : `Couldn’t ${kind} #${channel.name}`, { description: errorText(error) });
            setBusy(false);
        }
    };
    return (
        <ShellDialog
            open
            onOpenChange={(o) => !o && !busy && onClose()}
            title={TEXT[kind].title(channel)}
            description={TEXT[kind].line}
            onSubmit={(e) => void submit(e)}
            footer={footer(onClose, busy ? 'Saving…' : kind === 'reopen' ? 'Reopen' : 'Save', unchanged || busy)}
            testId="channel-setting"
        >
            <div className="pb-3 pt-1">
                <span className="relative block">
                    {named && <Hash className="pointer-events-none absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" strokeWidth={2} />}
                    <input
                        // eslint-disable-next-line jsx-a11y/no-autofocus -- the dialog opens to type
                        autoFocus
                        value={text}
                        onChange={(e) => setText(e.target.value)}
                        aria-label={named ? 'Name' : 'Topic'}
                        maxLength={named ? 80 : 250}
                        className={cn(PILL_FIELD, named && 'pl-10')}
                    />
                </span>
                {named && text.trim() && slug !== text.trim() && <span className="mt-1.5 block px-4 text-[12.5px] text-muted-foreground">Saved as #{slug || '…'}</span>}
            </div>
        </ShellDialog>
    );
}

function footer(onClose: () => void, label: string, disabled: boolean) {
    return (
        <>
            <button type="button" onClick={onClose} className={BUTTON_GHOST}>
                Cancel
            </button>
            <button type="submit" disabled={disabled} className={BUTTON_PRIMARY}>
                {label}
            </button>
        </>
    );
}

/** Reads what a call does, as the platform previews it (null while it's read; a failure says so and lets it go on). */
export function usePreview(path: string, method = 'DELETE'): { impact: Impact | null; failed: string | null } {
    const client = useWorkClient();
    const [impact, setImpact] = useState<Impact | null>(null);
    const [failed, setFailed] = useState<string | null>(null);
    useEffect(() => {
        let live = true;
        previewCall(client, path, method).then(
            (found) => live && setImpact(found),
            (error: unknown) => live && setFailed(errorText(error))
        );
        return () => {
            live = false;
        };
    }, [client, path, method]);
    return { impact, failed };
}

/** Delete, after the platform's preview of what stops with it; a toast's Undo takes it back out of the trash. */
function DeleteChannel({ channel, channels, onClose, onGone }: { channel: Channel; channels: Channels; onClose: () => void; onGone: () => void }) {
    const { impact, failed } = usePreview(`/v1/channels/${encodeURIComponent(channel.id)}`);
    const confirm = async () => {
        try {
            const { trashId } = await channels.deleteChannel(channel.id);
            onGone();
            toast(`#${channel.name} is in the trash`, {
                description: impact?.undo ?? 'Restorable from the trash for 30 days.',
                action: {
                    label: 'Undo',
                    onClick: () => void channels.restoreChannel(trashId).catch((error: unknown) => toast(`Couldn’t put #${channel.name} back`, { description: errorText(error) })),
                },
            });
        } catch (error) {
            toast(`Couldn’t delete #${channel.name}`, { description: errorText(error) });
        }
    };
    return <PreviewedDelete title={`Delete #${channel.name}?`} noun="Channel" confirmLabel={`Delete #${channel.name}`} impact={impact} failed={failed} onClose={onClose} onConfirm={() => void confirm()} testId="delete-channel" />;
}

/** The one delete confirm, saying what the platform's preview says goes and what stops with it. */
export function PreviewedDelete({
    title,
    noun,
    confirmLabel,
    impact,
    failed,
    onClose,
    onConfirm,
    testId,
}: {
    title: string;
    noun: string;
    confirmLabel: string;
    impact: Impact | null;
    failed: string | null;
    onClose: () => void;
    onConfirm: () => void;
    testId: string;
}) {
    return (
        <DeleteConfirmPopup
            isOpen
            onOpenChange={(open) => !open && onClose()}
            itemType={noun}
            title={title}
            confirmLabel={confirmLabel}
            softDelete={impact?.reversible !== false}
            customMessage={impact?.deletes || (failed ? undefined : 'Reading what goes with it…')}
            subText={impact ? (impact.reversible ? (impact.undo ?? 'Restorable from the trash for 30 days.') : 'This can’t be undone.') : ''}
            confirmDisabled={!impact && !failed}
            onConfirmDelete={onConfirm}
            testId={testId}
        >
            {impact && <ImpactList impact={impact} />}
            {failed && (
                <p role="alert" className="mt-1.5 text-[13px] text-red-600 dark:text-red-400">
                    Couldn’t read what goes with it: {failed}
                </p>
            )}
        </DeleteConfirmPopup>
    );
}

/** What stops or is lost with it, in the platform's own words. */
function ImpactList({ impact }: { impact: Impact }) {
    if (!impact.dependsOnIt.length && !impact.dataLost.length) return null;
    return (
        <div className="mt-2.5 space-y-2 text-[13.5px] leading-snug" data-testid="impact">
            {impact.dependsOnIt.length > 0 && (
                <ul className="space-y-1 rounded-2xl bg-foreground/[0.04] px-4 py-3">
                    {impact.dependsOnIt.map((d) => (
                        <li key={d} className="flex gap-2">
                            <span aria-hidden className="mt-[7px] h-1 w-1 shrink-0 rounded-full bg-foreground/50" />
                            {d}
                        </li>
                    ))}
                </ul>
            )}
            {impact.dataLost.length > 0 && <p className="text-muted-foreground">Lost for good: {impact.dataLost.join(', ')}.</p>}
        </div>
    );
}

/** A read-only foot, in the box's place, with its way back where you have one. */
function ReadOnlyFoot({ icon: Icon, lead, children, action, testId }: { icon: LucideIcon; lead: string; children: ReactNode; action?: { label: string; onClick: () => void }; testId: string }) {
    return (
        <div className="px-3 pb-4 pt-1 sm:px-5" data-testid={testId}>
            <div className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-[26px] bg-foreground/[0.04] px-5 py-3.5 ring-1 ring-inset ring-border dark:ring-foreground/[0.08]">
                <Icon className="h-4 w-4 shrink-0 text-muted-foreground" strokeWidth={1.9} />
                <p className="min-w-0 flex-1 text-[13.5px] leading-snug text-muted-foreground">
                    <span className="font-medium text-foreground">{lead}</span> {children}
                </p>
                {action && (
                    <button type="button" onClick={action.onClick} className={cn(BUTTON_SECONDARY, 'h-8 px-3.5 text-[13px]')}>
                        {action.label}
                    </button>
                )}
            </div>
        </div>
    );
}

/** A closed channel's foot: everyone reads it, no one posts; `onReopen` where you may reopen it. */
export function ClosedFooter({ channel, onReopen }: { channel: Channel; onReopen?: () => void }) {
    return (
        <ReadOnlyFoot icon={Lock} lead={`#${channel.name} is closed.`} action={onReopen && { label: 'Reopen', onClick: onReopen }} testId="channel-closed">
            Everyone can read it. No one can post, and its agents don’t answer here.
        </ReadOnlyFoot>
    );
}

/** The foot of every channel in an archived space; `onUnarchive` where it's yours. */
export function ArchivedFooter({ spaceName, onUnarchive }: { spaceName: string; onUnarchive?: () => void }) {
    return (
        <ReadOnlyFoot icon={Archive} lead={`${spaceName} is archived.`} action={onUnarchive && { label: 'Unarchive', onClick: onUnarchive }} testId="space-archived">
            Everything in it stays readable. Nothing new can be posted.
        </ReadOnlyFoot>
    );
}
