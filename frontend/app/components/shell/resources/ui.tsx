// The pieces every detail page is built from (a resource, a connected
// account): a titled section, the quiet surface that holds a list, a table or
// a file, a chip that opens an automation, a destructive action that asks
// once, in place, a choice of one of a few things, and the link to another
// item's page; and a body's way back up a level inside its resource.
import { createContext, useContext, useEffect, useId, useRef, useState, type ReactNode } from 'react';
import { Link, useSearchParams } from 'react-router';
import { Bot, ChevronDown, Trash2, type LucideIcon } from 'lucide-react';
import { MarkRow } from '~/components/dashboard/primitives';
import type { WorkflowRef } from '~/components/dashboard/types';
import { RadioGroup, RadioGroupItem } from '~/components/ui/radio-group';
import { navigateToWorkflow } from '~/lib/navigation';
import { cn } from '~/lib/utils';
import { useInPhoneShell } from '../AppShell';
import { BUTTON_DANGER, BUTTON_GHOST, BUTTON_SECONDARY } from '../buttons';
import { INNER_PARAMS, kindDef, type KindId } from './kinds';
import type { ResourceUser } from './model';
import { impactRows, usePlatformResources, type DeletionImpact, type Removal } from './platform';

export interface InnerStep {
    label: string;
    onBack: () => void;
}

/** Set by a detail page around its body: where the phone bar's way back goes instead of out of the resource. */
export const InnerBackContext = createContext<((step: InnerStep | null) => void) | null>(null);

/**
 * A resource's body a level down inside it (a repo's history, one commit): the phone bar's way back leads up a
 * level there rather than out of the resource. Renders nothing.
 */
export function ResourceInnerBack({ label, onBack }: InnerStep) {
    const set = useContext(InnerBackContext);
    const latest = useRef(onBack);
    latest.current = onBack;
    useEffect(() => {
        if (!set) return;
        set({ label, onBack: () => latest.current() });
        return () => set(null);
    }, [set, label]);
    return null;
}

/** A body a level down inside its resource (a table's rows, a query): the phone bar's way back, and the trail above it elsewhere. */
export function InnerLevel({ label, onBack, trail, children }: { label: string; onBack: () => void; trail: TrailStep[]; children: ReactNode }) {
    const inPhone = useInPhoneShell();
    return (
        <div className="mt-10 space-y-4">
            <ResourceInnerBack label={label} onBack={onBack} />
            {!inPhone && <Trail steps={trail} />}
            {children}
        </div>
    );
}

export interface TrailStep {
    label: string;
    onGo?: () => void;
    mono?: boolean;
}

/** Where a body is a level or two down inside its resource ("booking / History / 3f2a1c9"): each step but the last goes back to it. */
export function Trail({ steps }: { steps: TrailStep[] }) {
    return (
        <nav aria-label="Where you are" className="flex min-w-0 flex-wrap items-center gap-0.5 text-[14px]">
            {steps.map((step, i) => (
                <span key={i} className="flex min-w-0 items-center gap-0.5">
                    {i > 0 && <span className="text-muted-foreground/60">/</span>}
                    {step.onGo ? (
                        <button type="button" onClick={step.onGo} className="rounded px-1 font-medium text-foreground/80 transition-colors hover:text-foreground hover:underline">
                            {step.label}
                        </button>
                    ) : (
                        <span className={cn('truncate px-1 font-semibold text-foreground', step.mono && 'font-mono text-[13.5px]')}>{step.label}</span>
                    )}
                </span>
            ))}
        </nav>
    );
}

/**
 * Where a body's folder (`dir`, ending in /, '' at the top) sits among its files: the phone bar's way up a level, and
 * elsewhere the trail to every folder above it. Nothing at the top.
 */
export function FolderTrail({ dir, onGo }: { dir: string; onGo: (dir: string) => void }) {
    const inPhone = useInPhoneShell();
    if (!dir) return null;
    const segments = dir.slice(0, -1).split('/');
    const upTo = (n: number) => (n ? `${segments.slice(0, n).join('/')}/` : '');
    return (
        <>
            <ResourceInnerBack label={segments.length > 1 ? segments[segments.length - 2] : 'Files'} onBack={() => onGo(upTo(segments.length - 1))} />
            {!inPhone && (
                <div className="mb-3">
                    <Trail steps={[{ label: 'Files', onGo: () => onGo('') }, ...segments.map((name, i) => ({ label: name, onGo: i < segments.length - 1 ? () => onGo(upTo(i + 1)) : undefined }))]} />
                </div>
            )}
        </>
    );
}

export function Section({ title, meta, action, className, children }: { title: string; meta?: ReactNode; action?: ReactNode; className?: string; children: ReactNode }) {
    return (
        <section className={cn('mt-10', className)}>
            <div className="mb-3 flex items-baseline justify-between gap-3">
                <h2 className="flex items-baseline gap-2 text-[15px] font-semibold tracking-[-0.01em] text-foreground">
                    {title}
                    {meta != null && <span className="text-[13px] font-normal tabular-nums text-muted-foreground">{meta}</span>}
                </h2>
                {action}
            </div>
            {children}
        </section>
    );
}

export function Surface({ children, className }: { children: ReactNode; className?: string }) {
    return <div className={cn('overflow-hidden rounded-2xl border border-border bg-card dark:border-foreground/[0.08] dark:bg-foreground/[0.02]', className)}>{children}</div>;
}

const CHIP = 'inline-flex h-9 max-w-full items-center gap-2 rounded-full bg-secondary pl-3 pr-4 text-[13.5px] text-foreground transition-colors dark:bg-foreground/[0.06]';
const CHIP_HOVER = 'hover:bg-accent dark:hover:bg-foreground/[0.1]';

export function WorkflowChip({ workflow }: { workflow: WorkflowRef }) {
    return (
        <button type="button" onClick={() => navigateToWorkflow({ id: workflow.id, name: workflow.name })} className={cn(CHIP, CHIP_HOVER)}>
            {workflow.marks.length ? <MarkRow types={workflow.marks} size="xs" max={3} hideRest /> : null}
            <span className="truncate">{workflow.name}</span>
        </button>
    );
}

/** An app or agent's mark, beside its name wherever it uses a resource. */
export function ResourceUserIcon({ user, className }: { user: Pick<ResourceUser, 'kind'>; className?: string }) {
    const Icon = user.kind === 'app' ? kindDef('apps').icon : Bot;
    return <Icon className={cn('h-3.5 w-3.5 shrink-0 text-muted-foreground', className)} strokeWidth={1.75} />;
}

/** What uses a platform resource: an app Resources lists opens its page; an agent, which has none here, only says so. */
export function ResourceUserChip({ user }: { user: ResourceUser }) {
    const link = useResourceLink();
    const apps = usePlatformResources()?.items.apps;
    const listed = user.kind === 'app' && !!apps?.some((a) => a.id === user.id);
    const body = (
        <>
            <ResourceUserIcon user={user} />
            <span className="truncate">{user.name}</span>
            {user.binding && (
                <span className="shrink-0 text-muted-foreground">
                    as <span className="font-mono text-[12.5px]">{user.binding}</span>
                </span>
            )}
        </>
    );
    if (listed) {
        return (
            <Link to={{ search: link('apps', user.id) }} aria-label={user.binding ? `${user.name} as ${user.binding}` : user.name} className={cn(CHIP, CHIP_HOVER)}>
                {body}
            </Link>
        );
    }
    return (
        <span className={CHIP} title={user.kind === 'agent' ? 'An agent with it in its tools' : undefined}>
            {body}
        </span>
    );
}

/** A list row's delete: a bin on hover, then Delete or Keep in its place. */
export function RowDelete({ name, asking, onAsk, onConfirm }: { name: string; asking: boolean; onAsk: (ask: boolean) => void; onConfirm: () => void }) {
    if (asking) {
        return (
            <span className="flex shrink-0 items-center gap-1 text-[12.5px]">
                <button type="button" className="rounded-full px-2.5 py-1 font-medium text-red-600 hover:bg-red-500/10 dark:text-red-400" onClick={onConfirm}>
                    Delete
                </button>
                <button type="button" className="rounded-full px-2.5 py-1 text-muted-foreground hover:text-foreground" onClick={() => onAsk(false)}>
                    Keep
                </button>
            </span>
        );
    }
    return (
        <button
            type="button"
            aria-label={`Delete ${name}`}
            onClick={() => onAsk(true)}
            className="shrink-0 rounded-full p-1.5 text-muted-foreground opacity-0 transition-opacity hover:text-red-600 focus-visible:opacity-100 group-hover:opacity-100 dark:hover:text-red-400"
        >
            <Trash2 className="h-4 w-4" />
        </button>
    );
}

/** A destructive action that asks once, in place: no modal. `quiet` for one on each row of a list: no pill, no icon. */
export function ConfirmAction({
    label,
    confirm,
    icon: Icon = Trash2,
    quiet,
    onConfirm,
}: {
    label: string;
    confirm: string;
    icon?: typeof Trash2;
    quiet?: boolean;
    onConfirm: () => Promise<void>;
}) {
    const [asking, setAsking] = useState(false);
    const [busy, setBusy] = useState(false);
    if (!asking) {
        return (
            <button type="button" className={cn(quiet ? BUTTON_GHOST : BUTTON_SECONDARY, 'hover:text-red-600 dark:hover:text-red-400')} onClick={() => setAsking(true)}>
                {!quiet && <Icon className="h-4 w-4" />}
                {label}
            </button>
        );
    }
    return (
        <span className="inline-flex items-center gap-1">
            <button
                type="button"
                disabled={busy}
                className="inline-flex h-9 items-center rounded-full bg-red-600 px-4 text-[13.5px] font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-60"
                onClick={async () => {
                    setBusy(true);
                    try {
                        await onConfirm();
                    } finally {
                        setBusy(false);
                        setAsking(false);
                    }
                }}
            >
                {confirm}
            </button>
            <button type="button" className="inline-flex h-9 items-center rounded-full px-3 text-[13.5px] text-muted-foreground transition-colors hover:text-foreground" onClick={() => setAsking(false)}>
                Cancel
            </button>
        </span>
    );
}

/** A removal asked in place under its page's header: what the platform says it does, then the confirm. */
export function RemovalPanel({ removal, onCancel, onDone }: { removal: Removal; onCancel: () => void; onDone: (result: { done: string; gone: boolean }) => void }) {
    const [impact, setImpact] = useState<DeletionImpact | null>(null);
    const [failed, setFailed] = useState<string | null>(null);
    const [busy, setBusy] = useState(false);
    useEffect(() => {
        let live = true;
        removal.preview().then(
            (found) => live && setImpact(found),
            (error: unknown) => live && setFailed(error instanceof Error ? error.message : String(error))
        );
        return () => {
            live = false;
        };
    }, [removal]);
    const confirm = async () => {
        setBusy(true);
        setFailed(null);
        try {
            onDone(await removal.run());
        } catch (error) {
            setFailed(error instanceof Error ? error.message : String(error));
            setBusy(false);
        }
    };
    return (
        <section aria-label={removal.confirm} data-testid="removal-panel" className="mt-6 rounded-xl border border-border bg-foreground/[0.03] px-4 py-3.5 dark:border-foreground/[0.08]">
            {impact ? (
                <div className="space-y-1 text-[13.5px] leading-snug">
                    <p className="m-0 text-foreground">{impact.deletes}</p>
                    {impactRows(impact).map(({ term, items }) => (
                        <p key={term} className="m-0">
                            <span className="text-muted-foreground">{term}: </span>
                            {items.join('; ')}
                        </p>
                    ))}
                    <p className="m-0 text-muted-foreground">{impact.undo ?? (impact.reversible ? 'It can be undone.' : 'It can’t be undone.')}</p>
                </div>
            ) : (
                !failed && <p className="m-0 text-[13.5px] text-muted-foreground">Checking what it would do…</p>
            )}
            {failed && (
                <p role="alert" className="m-0 mt-2 text-[13px] text-red-600 dark:text-red-400">
                    {failed}
                </p>
            )}
            <div className="mt-3 flex flex-wrap items-center gap-1">
                <button type="button" className={BUTTON_DANGER} disabled={busy || !impact} onClick={() => void confirm()}>
                    {removal.confirm}
                </button>
                <button type="button" className={BUTTON_GHOST} onClick={onCancel}>
                    Cancel
                </button>
            </div>
        </section>
    );
}

/** A quiet pill that picks one of a few values (a branch, a column, a level), its menu the browser's own. */
export function PillSelect<T extends string>({
    label,
    value,
    options,
    onChange,
    icon: Icon,
    className,
}: {
    label: string;
    value: T;
    options: readonly { value: T; label: string }[];
    onChange: (value: T) => void;
    icon?: LucideIcon;
    className?: string;
}) {
    return (
        <label
            className={cn(
                'relative inline-flex h-8 min-w-0 items-center gap-1.5 rounded-full bg-foreground/[0.05] pl-3 pr-2.5 text-[13px] font-medium text-foreground ring-1 ring-inset ring-foreground/[0.06] focus-within:ring-2 focus-within:ring-ring',
                className
            )}
        >
            {Icon && <Icon className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />}
            <span className="max-w-[12rem] truncate">{options.find((o) => o.value === value)?.label ?? value}</span>
            <ChevronDown className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
            <select aria-label={label} value={value} onChange={(e) => onChange(e.target.value as T)} className="absolute inset-0 cursor-pointer opacity-0">
                {options.map((o) => (
                    <option key={o.value} value={o.value}>
                        {o.label}
                    </option>
                ))}
            </select>
        </label>
    );
}

export interface Choice {
    value: string;
    title: ReactNode;
    detail?: ReactNode;
}

/** One of a few things, picked by its row: no card around them, a hairline between them. */
export function ChoiceList({ label, choices, value, onChange }: { label: string; choices: Choice[]; value: string | null; onChange: (value: string) => void }) {
    const id = useId();
    return (
        <RadioGroup aria-label={label} value={value ?? ''} onValueChange={onChange} className="gap-0 divide-y divide-border dark:divide-foreground/[0.06]">
            {choices.map((c) => (
                <label key={c.value} htmlFor={`${id}-${c.value}`} className="flex cursor-pointer items-center gap-3 py-3">
                    <RadioGroupItem id={`${id}-${c.value}`} value={c.value} />
                    <span className="min-w-0 flex-1">
                        <span className="block truncate text-[14px] text-foreground">{c.title}</span>
                        {c.detail && <span className="block truncate text-[12.5px] text-muted-foreground">{c.detail}</span>}
                    </span>
                </label>
            ))}
        </RadioGroup>
    );
}

/** Where another item's page is, as a link's search: a step Back undoes. */
export function useResourceLink(): (kind: KindId, id: string) => string {
    const [params] = useSearchParams();
    return (kind, id) => {
        const next = new URLSearchParams(params);
        next.set('kind', kind);
        next.set('resource', id);
        // Where a body was inside the item it was opened in (a repo's path and branch, a database's table) stays there.
        for (const inner of INNER_PARAMS) next.delete(inner);
        return `?${next.toString()}`;
    };
}
