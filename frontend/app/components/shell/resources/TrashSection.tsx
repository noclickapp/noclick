// A kind's trash, under its list: what was deleted and when it goes for good,
// each one restorable or purged now. Restoring is free; until then it's stored,
// and billed, as before.
import { useState } from 'react';
import { RotateCcw } from 'lucide-react';
import { relTime } from '~/components/dashboard/primitives';
import { BUTTON_GHOST } from '../buttons';
import type { TrashEntry } from './platform';
import { ConfirmAction, Section } from './ui';

export function TrashSection({
    entries,
    now,
    onRestore,
    onPurge,
}: {
    entries: TrashEntry[];
    now: string;
    onRestore: (entry: TrashEntry) => Promise<void>;
    onPurge: (entry: TrashEntry) => Promise<void>;
}) {
    return (
        <Section title="Trash" meta={entries.length} className="mt-12">
            <div
                data-testid="resources-trash"
                className="divide-y divide-border overflow-hidden rounded-2xl border border-border bg-card dark:divide-foreground/[0.06] dark:border-foreground/[0.08] dark:bg-foreground/[0.02]"
            >
                {entries.map((entry) => (
                    <TrashRow key={entry.id} entry={entry} now={now} onRestore={onRestore} onPurge={onPurge} />
                ))}
            </div>
            <p className="mt-2 text-[12.5px] text-muted-foreground">Each is restorable for 30 days after it’s deleted, then gone for good.</p>
        </Section>
    );
}

function TrashRow({ entry, now, onRestore, onPurge }: { entry: TrashEntry; now: string; onRestore: (entry: TrashEntry) => Promise<void>; onPurge: (entry: TrashEntry) => Promise<void> }) {
    const [busy, setBusy] = useState(false);
    const [failed, setFailed] = useState<string | null>(null);
    const act = async (action: (entry: TrashEntry) => Promise<void>) => {
        setBusy(true);
        setFailed(null);
        try {
            await action(entry);
        } catch (error) {
            setFailed(error instanceof Error ? error.message : String(error));
            setBusy(false);
        }
    };
    const when = [entry.trashedAt && `Deleted ${relTime(entry.trashedAt, now)}`, entry.purgeAfter && `gone for good ${relTime(entry.purgeAfter, now)}`].filter(Boolean).join(' · ');
    return (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-3" data-testid={`trash-row-${entry.id}`}>
            <span className="min-w-0 flex-1">
                <span className="block truncate text-[14px] font-medium text-foreground">{entry.name}</span>
                {when && <span className="block truncate text-[12.5px] text-muted-foreground">{when}</span>}
                {failed && (
                    <span role="alert" className="block text-[12.5px] text-red-600 dark:text-red-400">
                        {failed}
                    </span>
                )}
            </span>
            <span className="flex items-center gap-1">
                <button type="button" className={BUTTON_GHOST} disabled={busy} onClick={() => void act(onRestore)}>
                    <RotateCcw className="h-4 w-4" />
                    Restore
                </button>
                <ConfirmAction quiet label="Purge now" confirm="Delete for good" onConfirm={() => act(onPurge)} />
            </span>
        </div>
    );
}
