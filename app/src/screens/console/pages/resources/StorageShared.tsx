// Pieces the Databases, Storage and Volumes panels share: sizes and
// counts as the tables print them, who uses a resource, the type-the-name
// delete for a resource that holds data, and the Export section.
import { useState, type ReactNode } from 'react';
import { Download } from 'lucide-react';
import { HAIRLINE } from '@/ui/primitives';
import { cn } from '@/ui/utils';
import type { ExportBundle, Operation, UsedBy } from 'noclick';
import { useConsole } from '@/screens/console/hooks/useConsole';
import { formatRelative } from '@/screens/console/lib/format';
import { ConsoleButton } from '../../ui/Button';
import { ConsoleDialog } from '../../ui/ConsoleDialog';
import { ErrorPanel } from '../../ui/ErrorPanel';
import { INPUT, Section, errorText } from './shared';

const UNITS = ['B', 'KB', 'MB', 'GB', 'TB'];

/** `1.8 GB`, `240 MB`, `48 KB`: binary units, one decimal below 100. */
export function formatSize(bytes: number | null | undefined): string {
    if (bytes == null) return '—';
    let value = bytes;
    let unit = 0;
    while (value >= 1024 && unit < UNITS.length - 1) {
        value /= 1024;
        unit++;
    }
    const shown = unit === 0 || value >= 100 ? Math.round(value) : Number(value.toFixed(1));
    return `${shown} ${UNITS[unit]}`;
}

const EXACT = new Intl.NumberFormat('en-US');

/** `18,204`. */
export function formatExact(n: number | null | undefined): string {
    return n == null ? '—' : EXACT.format(n);
}

/** What binds a database or bucket: `booking as DB, concierge (agent)`. */
export function UsedByText({ users }: { users: readonly UsedBy[] }) {
    if (!users.length) return <span className="text-muted-foreground">Nothing yet</span>;
    return (
        <span className="min-w-0 truncate">
            {users.map((u, i) => (
                <span key={`${u.id}:${u.binding}`}>
                    {i > 0 && ', '}
                    {u.name}
                    {u.binding ? (
                        <span className="text-muted-foreground">
                            {' '}
                            as <span className="font-mono text-[12px]">{u.binding}</span>
                        </span>
                    ) : (
                        u.kind === 'agent' && <span className="text-muted-foreground"> (agent)</span>
                    )}
                </span>
            ))}
        </span>
    );
}

/**
 * Deleting a resource that holds data: the consequence stated, the name typed to
 * confirm, and the API's refusal (an app still binds it) shown in place.
 */
export function DeleteByName({
    label,
    name,
    description,
    onConfirm,
}: {
    label: string;
    name: string;
    description: ReactNode;
    onConfirm: () => Promise<void>;
}) {
    const [open, setOpen] = useState(false);
    const [typed, setTyped] = useState('');
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<unknown>(undefined);
    const close = (next: boolean) => {
        if (!next) {
            setTyped('');
            setError(undefined);
        }
        setOpen(next);
    };
    const run = async () => {
        setBusy(true);
        setError(undefined);
        try {
            await onConfirm();
            close(false);
        } catch (e) {
            setError(e);
        } finally {
            setBusy(false);
        }
    };
    return (
        <>
            <ConsoleButton variant="danger" size="sm" onClick={() => setOpen(true)}>
                {label}
            </ConsoleButton>
            <ConsoleDialog
                open={open}
                onOpenChange={close}
                size="sm"
                title={`Delete ${name}?`}
                description={description}
                footer={
                    <>
                        <ConsoleButton variant="ghost" onClick={() => close(false)}>
                            Cancel
                        </ConsoleButton>
                        <ConsoleButton variant="danger" disabled={busy || typed !== name} onClick={() => void run()}>
                            {busy ? 'Deleting…' : label}
                        </ConsoleButton>
                    </>
                }
            >
                <div className="flex flex-col gap-3">
                    <label className="flex flex-col gap-1.5">
                        <span className="text-[12px] text-muted-foreground">
                            Type <span className="font-mono text-foreground">{name}</span> to confirm
                        </span>
                        <input value={typed} onChange={(e) => setTyped(e.target.value)} aria-label={`Type ${name} to confirm`} autoComplete="off" className={cn(INPUT, 'font-mono')} />
                    </label>
                    {error !== undefined && <ErrorPanel error={error} />}
                </div>
            </ConsoleDialog>
        </>
    );
}

/** Starts an export and, once the operation settles, links the bundle. */
export function ExportSection({ what, start }: { what: ReactNode; start: () => Promise<Operation<ExportBundle>> }) {
    const { now } = useConsole();
    const [state, setState] = useState<{ busy: boolean; bundle: ExportBundle | null; error: string | null }>({ busy: false, bundle: null, error: null });
    const run = async () => {
        setState({ busy: true, bundle: null, error: null });
        try {
            const bundle = await (await start()).wait();
            setState({ busy: false, bundle, error: null });
        } catch (e) {
            setState({ busy: false, bundle: null, error: errorText(e) });
        }
    };
    const { bundle } = state;
    return (
        <Section title="Export">
            <div className="flex flex-wrap items-center gap-3">
                <p className="m-0 min-w-0 flex-1 text-[13px] text-muted-foreground">{what}</p>
                <ConsoleButton size="sm" disabled={state.busy} onClick={() => void run()}>
                    {state.busy ? 'Preparing…' : bundle ? 'Export again' : 'Export'}
                </ConsoleButton>
            </div>
            {state.error && <p className="m-0 mt-2 text-[12px] text-red-600 dark:text-red-400">{state.error}</p>}
            {bundle?.url && (
                <div className={cn('mt-2 flex flex-col gap-1 rounded-lg border px-3 py-2.5', HAIRLINE)}>
                    <a href={bundle.url} className="inline-flex items-center gap-1.5 text-[13px] font-medium text-foreground underline-offset-2 hover:underline">
                        <Download className="h-3.5 w-3.5" />
                        Download the export
                    </a>
                    {bundle.contents.map((item) => (
                        <p key={`${item.kind}:${item.name}`} className="m-0 text-[12px] text-muted-foreground">
                            {item.detail}
                        </p>
                    ))}
                    {bundle.expiresAt && <p className="m-0 text-[12px] text-muted-foreground">The link expires {formatRelative(bundle.expiresAt, now())}.</p>}
                </div>
            )}
        </Section>
    );
}
