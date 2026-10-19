// One record in full, in a panel over the page's right edge: a row of a table,
// a deployment of an app. Every field is named over its type and shown whole:
// long text wraps, JSON is indented, a timestamp that names its zone also
// reads in the reader's time, NULL and bytes say so, and a secret-looking
// value stays hidden until asked. Each value copies. Rows beside it are a step
// away, so a page of them reads without closing the panel.
import type { ReactNode } from 'react';
import { ChevronDown, ChevronUp } from 'lucide-react';
import { CopyButton } from '~/components/ui/CopyButton';
import { cn } from '~/lib/utils';
import { SidePanel } from '../SidePanel';
import { localTime, shownValue } from './cells';
import { HiddenValue } from './DataGrid';

export interface RecordField {
    name: string;
    type?: string;
    value: unknown;
    /** Hidden until `onReveal`: the value looks secret. */
    hidden?: boolean;
    onReveal?: () => void;
    /** Shown in place of the value (a link), which still copies. */
    display?: ReactNode;
    /** Offers a copy: every field of a row does, only what is worth pasting of an object (its commit, its address). */
    copy?: boolean;
}

/** How a record's fields are named: `code` for a row's columns, `words` for an object's facts ("Status", "Branch"). */
export type FieldNames = 'code' | 'words';

function FieldValue({ field, names }: { field: RecordField; names: FieldNames }) {
    if (field.hidden && field.onReveal && field.value != null) return <HiddenValue onShow={field.onReveal} className="mx-0 -ml-1.5 text-[13px]" />;
    if (field.display !== undefined) return <div className="text-[14px] text-foreground [overflow-wrap:anywhere]">{field.display}</div>;
    const shown = shownValue(field.value, field.type);
    if (shown.kind === 'null' || shown.kind === 'binary') return <p className="m-0 font-mono text-[13px] text-muted-foreground">{shown.full}</p>;
    const local = localTime(field.value);
    return (
        <>
            <pre
                className={cn(
                    'm-0 whitespace-pre-wrap break-words font-mono text-[13px] leading-relaxed text-foreground [overflow-wrap:anywhere]',
                    names === 'words' && shown.kind !== 'json' && 'font-sans text-[14px]',
                    shown.kind === 'json' && 'max-h-[28rem] overflow-auto rounded-lg bg-foreground/[0.035] px-3 py-2 text-[12.5px] scrollbar-subtle'
                )}
            >
                {shown.full === '' ? <span className="font-sans text-muted-foreground">Empty text</span> : shown.full}
            </pre>
            {local && <p className="m-0 mt-1 text-[12.5px] text-muted-foreground">{local}, your time</p>}
        </>
    );
}

/** Copies what the value is, as text: JSON as JSON, nothing for NULL. */
function copyText(field: RecordField): string | null {
    if (field.value === null || field.value === undefined || (field.hidden && field.onReveal)) return null;
    return typeof field.value === 'object' ? JSON.stringify(field.value, null, 2) : String(field.value);
}

export function RecordFields({ fields, names = 'code' }: { fields: readonly RecordField[]; names?: FieldNames }) {
    return (
        <dl className="m-0 divide-y divide-border border-y border-border dark:divide-foreground/[0.06] dark:border-foreground/[0.06]">
            {fields.map((field) => {
                const copy = (field.copy ?? names === 'code') ? copyText(field) : null;
                return (
                    <div key={field.name} className="py-3.5">
                        <dt className="flex min-h-7 items-center gap-2">
                            <span className={cn('min-w-0 truncate', names === 'code' ? 'font-mono text-[12.5px] font-medium text-foreground/85' : 'text-[12.5px] text-muted-foreground')}>{field.name}</span>
                            {field.type && <span className="shrink-0 font-mono text-[11.5px] lowercase text-muted-foreground">{field.type}</span>}
                            {copy !== null && <CopyButton value={copy} className="-my-1 ml-auto [&_svg]:h-3.5 [&_svg]:w-3.5" />}
                        </dt>
                        <dd className="m-0 mt-1">
                            <FieldValue field={field} names={names} />
                        </dd>
                    </div>
                );
            })}
        </dl>
    );
}

/** The records beside the open one: a step up or down, and where it is ("Row 3 of 50"). */
export interface RecordSteps {
    where: string;
    onPrevious?: () => void;
    onNext?: () => void;
}

const STEP = 'inline-flex h-8 w-8 items-center justify-center rounded-full text-muted-foreground transition-colors hover:bg-foreground/[0.06] hover:text-foreground disabled:pointer-events-none disabled:opacity-35 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring';

export function RecordDrawer({
    open,
    onOpenChange,
    title,
    description,
    fields,
    names,
    steps,
    actions,
    note,
    children,
}: {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    title: string;
    description?: string;
    fields: readonly RecordField[];
    names?: FieldNames;
    steps?: RecordSteps;
    /** What can be done with the record (a file's preview and download), above its fields. */
    actions?: ReactNode;
    /** A line under the fields (why some are hidden). */
    note?: ReactNode;
    /** Sections under the fields (a deployment's log). */
    children?: ReactNode;
}) {
    return (
        <SidePanel open={open} onOpenChange={onOpenChange} title={title} description={description}>
            {steps && (
                <div className="-mt-2 mb-4 flex items-center gap-1">
                    <button type="button" aria-label="Previous row" className={STEP} disabled={!steps.onPrevious} onClick={steps.onPrevious}>
                        <ChevronUp className="h-4 w-4" />
                    </button>
                    <button type="button" aria-label="Next row" className={STEP} disabled={!steps.onNext} onClick={steps.onNext}>
                        <ChevronDown className="h-4 w-4" />
                    </button>
                    <span className="ml-1 text-[12.5px] tabular-nums text-muted-foreground">{steps.where}</span>
                </div>
            )}
            {actions && <div className="mb-5 flex flex-wrap items-center gap-2">{actions}</div>}
            <RecordFields fields={fields} names={names} />
            {note && <p className="m-0 mt-3 text-[12.5px] leading-snug text-muted-foreground">{note}</p>}
            {children}
        </SidePanel>
    );
}
