// A space's own settings from its menu: archiving one of yours (everything stays readable, nothing is posted, and it
// unarchives at any time), deleting one to the trash after the platform's preview of what goes with it, and leaving
// one you joined. Each says what happened, and offers it back where it comes back. Your personal space has none.
import { toast } from 'sonner';
import { Archive, LogOut } from 'lucide-react';
import { useState, type FormEvent } from 'react';
import { BUTTON_DANGER, BUTTON_GHOST, BUTTON_PRIMARY } from '@/ui/buttons';
import { ShellDialog } from '@/ui/ShellDialog';
import { errorText } from '@/screens/console/pages/resources/shared';
import { PreviewedDelete, usePreview } from './channels/settings';
import type { Spaces, WorkSpace } from './spaces';

export type SpaceAsk = 'archive' | 'leave' | 'delete';

/** Asks before archiving, deleting or leaving `space`. One that's gone leaves the list, and Work moves on from it. */
export function SpaceSettingsDialog({ ask, space, spaces, onClose }: { ask: SpaceAsk; space: WorkSpace; spaces: Spaces; onClose: () => void }) {
    if (ask === 'delete') return <DeleteSpace space={space} spaces={spaces} onClose={onClose} />;
    return <Confirm ask={ask} space={space} spaces={spaces} onClose={onClose} />;
}

/** Makes an archived space of yours active again, at once. */
export function unarchiveSpace(spaces: Spaces, space: WorkSpace) {
    return spaces.archive(space, false).then(
        () => toast(`Unarchived ${space.name}`, { description: 'Everyone can post in it again.' }),
        (error: unknown) => toast(`Couldn’t unarchive ${space.name}`, { description: errorText(error) })
    );
}

function Confirm({ ask, space, spaces, onClose }: { ask: 'archive' | 'leave'; space: WorkSpace; spaces: Spaces; onClose: () => void }) {
    const [busy, setBusy] = useState(false);
    const archive = ask === 'archive';
    const submit = async (e: FormEvent) => {
        e.preventDefault();
        if (busy) return;
        setBusy(true);
        try {
            if (archive) {
                await spaces.archive(space, true);
                toast(`Archived ${space.name}`, { description: 'Everything is readable. Nothing new can be posted.', action: { label: 'Undo', onClick: () => void unarchiveSpace(spaces, space) } });
            } else {
                await spaces.leave(space);
                toast(`You left ${space.name}`, { description: 'Someone there can invite you back.' });
            }
            onClose();
        } catch (error) {
            toast(`Couldn’t ${ask} ${space.name}`, { description: errorText(error) });
            setBusy(false);
        }
    };
    return (
        <ShellDialog
            open
            onOpenChange={(o) => !o && !busy && onClose()}
            tone={archive ? 'neutral' : 'danger'}
            mark={archive ? <Archive className="h-5 w-5" strokeWidth={1.75} /> : <LogOut className="h-5 w-5" strokeWidth={1.75} />}
            title={`${archive ? 'Archive' : 'Leave'} ${space.name}?`}
            description={
                archive
                    ? 'Everything in it stays readable, for everyone in it. No one can post, and its agents stop answering in its channels. You can unarchive it any time.'
                    : 'Its channels and your DMs there go from your Work. The space carries on, and someone in it can invite you back.'
            }
            onSubmit={(e) => void submit(e)}
            testId={archive ? 'archive-space' : 'leave-space'}
            footer={
                <>
                    <button type="button" onClick={onClose} className={BUTTON_GHOST}>
                        Cancel
                    </button>
                    <button type="submit" disabled={busy} className={archive ? BUTTON_PRIMARY : BUTTON_DANGER}>
                        {archive ? 'Archive' : `Leave ${space.name}`}
                    </button>
                </>
            }
        />
    );
}

function DeleteSpace({ space, spaces, onClose }: { space: WorkSpace; spaces: Spaces; onClose: () => void }) {
    const { impact, failed } = usePreview(`/v1/workspaces/${encodeURIComponent(space.workspaceId ?? '')}`);
    const confirm = async () => {
        try {
            const { trashId } = await spaces.remove(space);
            toast(`${space.name} is in the trash`, {
                description: 'For 30 days, with its channels. Your agents stay in your account.',
                action: { label: 'Undo', onClick: () => void spaces.restore(trashId).catch((error: unknown) => toast(`Couldn’t put ${space.name} back`, { description: errorText(error) })) },
            });
        } catch (error) {
            toast(`Couldn’t delete ${space.name}`, { description: errorText(error) });
        }
    };
    return <PreviewedDelete title={`Delete ${space.name}?`} noun="Space" confirmLabel={`Delete ${space.name}`} impact={impact} failed={failed} onClose={onClose} onConfirm={() => void confirm()} testId="delete-space" />;
}

/** Atop an archived space's list. */
export function ArchivedBanner() {
    return (
        <div data-rail-hide className="mb-2 flex items-start gap-2 rounded-xl bg-foreground/[0.05] px-3 py-2.5 text-[12.5px] leading-snug text-muted-foreground" data-testid="space-archived-banner">
            <Archive className="mt-0.5 h-3.5 w-3.5 shrink-0" strokeWidth={1.9} />
            <span>
                <span className="font-medium text-foreground">Archived.</span> Read anything here; nothing new can be posted.
            </span>
        </div>
    );
}
