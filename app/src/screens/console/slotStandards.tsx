// What stands in the console's slots when no host fills them (slots.ts).
import { useState } from 'react';
import type { CardProgram } from 'noclick';
import { relTime } from '@/lib/formatters';
import { getNodeIconMeta } from '@/lib/nodeIconRegistry';
import { HAIRLINE, NodeMark, nodeLabel, type MarkSize } from '@/ui/primitives';
import { cn } from '@/ui/utils';
import { ConsoleButton, consoleButtonClass } from './ui/Button';
import { PageSection } from './ui/PageHeader';
import { ConfirmAction } from './pages/resources/shared';
import type { AppsTrashProps, TrashEntry } from './slots';

/** The mark the icon registry holds for the service's node type: a plain cube when it holds none. */
export function StandardCredentialMark({ nodeType, size = 'sm', className }: { credentialType: string; nodeType?: string | null; size?: MarkSize; className?: string }) {
    return <NodeMark type={nodeType ?? ''} size={size} className={className} />;
}

/** The service's name as the icon registry has it, else read off its type: `automation-google-sheets` is
 *  "Google sheets". */
export function standardCredentialLabel(credentialType: string, nodeType?: string | null): string {
    if (nodeType && getNodeIconMeta(nodeType)) return nodeLabel(nodeType);
    const words = (nodeType || credentialType).replace(/^automation-/, '').replace(/[-_]+/g, ' ').trim();
    return words ? words.charAt(0).toUpperCase() + words.slice(1) : '';
}

/** Where the company finishes its application for card issuing: the issuer's form isn't part of this app. */
export function IssuerLink({ program }: { program: CardProgram }) {
    return (
        <div className="flex flex-col items-start gap-3">
            <p className="m-0 max-w-xl text-[13px] text-muted-foreground">The card issuer takes these details in its own form, which a person signed in to NoClick fills in on NoClick&apos;s console.</p>
            {program.onboardingUrl && (
                <a href={program.onboardingUrl} target="_blank" rel="noreferrer" className={consoleButtonClass('primary')}>
                    Continue the application
                </a>
            )}
        </div>
    );
}

function TrashRow({ entry, now, onRestore, onPurge }: { entry: TrashEntry } & Omit<AppsTrashProps, 'entries'>) {
    const [busy, setBusy] = useState(false);
    const [failed, setFailed] = useState<string | null>(null);
    const restore = async () => {
        setBusy(true);
        setFailed(null);
        try {
            await onRestore(entry);
        } catch (error) {
            setFailed(error instanceof Error ? error.message : String(error));
            setBusy(false);
        }
    };
    const when = [entry.trashedAt && `Deleted ${relTime(entry.trashedAt, now)}`, entry.purgeAfter && `gone for good ${relTime(entry.purgeAfter, now)}`].filter(Boolean).join(' · ');
    return (
        <li className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2.5">
            <span className="min-w-0 flex-1 basis-48">
                <span className="block truncate text-[13px] font-medium text-foreground">{entry.name}</span>
                {when && <span className="block truncate text-[12px] text-muted-foreground">{when}</span>}
                {failed && (
                    <span role="alert" className="block text-[12px] text-red-600 dark:text-red-400">
                        {failed}
                    </span>
                )}
            </span>
            <span className="flex items-center gap-2">
                <ConsoleButton size="sm" disabled={busy} onClick={() => void restore()}>
                    Restore
                </ConsoleButton>
                <ConfirmAction
                    label="Purge now"
                    title={`Delete ${entry.name} for good?`}
                    description="It can't be restored after this."
                    confirmLabel="Delete for good"
                    onConfirm={() => onPurge(entry)}
                />
            </span>
        </li>
    );
}

/** The apps in the trash as a plain list: when each was deleted and when it goes for good, to restore or purge now. */
export function StandardAppsTrash({ entries, now, onRestore, onPurge }: AppsTrashProps) {
    return (
        <PageSection title="Trash" count={entries.length} note="Each is restorable for 30 days after it’s deleted, then gone for good.">
            <ul aria-label="Apps in the trash" className={cn('m-0 list-none divide-y divide-border rounded-lg border p-0', HAIRLINE)}>
                {entries.map((entry) => (
                    <TrashRow key={entry.id} entry={entry} now={now} onRestore={onRestore} onPurge={onPurge} />
                ))}
            </ul>
        </PageSection>
    );
}
