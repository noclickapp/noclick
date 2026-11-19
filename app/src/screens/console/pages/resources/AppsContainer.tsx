// The Apps drawer's container settings: what each instance gets (vCPUs and memory), how many are kept warm and how many
// it may grow to, whether its CPU runs between requests, and how long a request may take, with what its warm instances
// cost a month with nothing calling it. Changed in a dialog that sends only what changed, a refusal shown under the
// setting it names; each release runs at the settings it was released with, so a change applies from the next one.
import { useEffect, useState } from 'react';
import { toast } from 'sonner';
import { cn } from '@/ui/utils';
import type { ContainerSettings, Project, ProjectContainer } from 'noclick';
import { formatMoney } from '@/screens/console/lib/format';
import { invalidateV1 } from '@/sdk/useV1';
import { ConsoleButton } from '../../ui/Button';
import { ConsoleDialog } from '../../ui/ConsoleDialog';
import { ErrorPanel } from '../../ui/ErrorPanel';
import { FormField, formError } from '../Users';
import type { ChoiceOption } from './AppsFormat';
import { Choice } from './AppsParts';
import { Field, INPUT, Section } from './shared';

const APPLIES = 'Each release runs at the settings it was released with, so a change applies from the next deploy, or a promote of what production serves.';
/** What the API says of an app pinned to the edge whose settings are changed; said here of one whose aren't too. */
const ON_THE_EDGE = "Its releases run on the edge, where these don't apply: they size its releases in a container.";

const DEFAULTS: Required<ContainerSettings> = { cpu: 1, memory: 512, minInstances: 0, maxInstances: 10, cpuAlways: false, requestTimeoutS: 300 };

type NumberKey = 'cpu' | 'memory' | 'minInstances' | 'maxInstances' | 'requestTimeoutS';
type SettingKey = NumberKey | 'cpuAlways';

/** Each number the dialog takes, with what it accepts. */
const NUMBERS: readonly { key: NumberKey; label: string; hint: string; decimal?: boolean }[] = [
    { key: 'cpu', label: 'vCPUs', hint: '1, 2, 4, 6 or 8; or 0.5 to 0.99, where each instance answers one request at a time.', decimal: true },
    { key: 'memory', label: 'Memory (MiB)', hint: 'From 512: up to 1024 under 1 vCPU, 4096 at 1, 8192 at 2, more at 4 to 8.' },
    { key: 'minInstances', label: 'Kept warm', hint: '0 to 3, running while production serves it, whether or not anything calls it.' },
    { key: 'maxInstances', label: 'Most instances', hint: '1 to 10 at once.' },
    { key: 'requestTimeoutS', label: 'Request timeout (seconds)', hint: '1 to 3600.' },
];

type CpuAlways = 'requests' | 'always';
const CPU_ALWAYS: readonly ChoiceOption<CpuAlways>[] = [
    { value: 'requests', label: 'Only during requests', sentence: 'Each instance is billed while it answers requests.' },
    { value: 'always', label: 'Always on', sentence: 'For work that goes on without a request, like a bot or a queue worker: each instance is billed from start to stop. Takes 1 vCPU or more.' },
];

const plural = (n: number, one: string, many = `${one}s`) => `${n.toLocaleString('en-US')} ${n === 1 ? one : many}`;

/** `300` → `5 minutes`; a count of seconds that isn't whole minutes stays in seconds. */
function seconds(s: number): string {
    if (s >= 3600 && s % 3600 === 0) return plural(s / 3600, 'hour');
    if (s >= 60 && s % 60 === 0) return plural(s / 60, 'minute');
    return plural(s, 'second');
}

/** The API's name for a setting (`container.min_instances`) as the dialog's (`minInstances`). */
const settingOf = (field: string | null): SettingKey | null => {
    const name = field?.startsWith('container.') ? field.slice('container.'.length).replace(/_([a-z])/g, (_, c: string) => c.toUpperCase()) : null;
    return name && (name === 'cpuAlways' || NUMBERS.some((n) => n.key === name)) ? (name as SettingKey) : null;
};

const isDefault = (c: ProjectContainer) => (Object.keys(DEFAULTS) as SettingKey[]).every((k) => c[k] === DEFAULTS[k]);

function ContainerDialog({ project, open, onOpenChange }: { project: Project; open: boolean; onOpenChange: (open: boolean) => void }) {
    const current = project.container;
    const [text, setText] = useState<Record<NumberKey, string>>({ cpu: '', memory: '', minInstances: '', maxInstances: '', requestTimeoutS: '' });
    const [cpuAlways, setCpuAlways] = useState<CpuAlways>('requests');
    const [errors, setErrors] = useState<Partial<Record<SettingKey, string>>>({});
    const [failure, setFailure] = useState<unknown>(undefined);
    const [busy, setBusy] = useState(false);
    useEffect(() => {
        if (!open) return;
        setText({ cpu: String(current.cpu), memory: String(current.memory), minInstances: String(current.minInstances), maxInstances: String(current.maxInstances), requestTimeoutS: String(current.requestTimeoutS) });
        setCpuAlways(current.cpuAlways ? 'always' : 'requests');
        setErrors({});
        setFailure(undefined);
    }, [open]); // eslint-disable-line react-hooks/exhaustive-deps
    const parsed = Object.fromEntries(NUMBERS.map(({ key }) => [key, text[key].trim() === '' ? NaN : Number(text[key])])) as Record<NumberKey, number>;
    const valid = NUMBERS.every(({ key }) => Number.isFinite(parsed[key]));
    // Only what changed goes: a setting left out keeps its value.
    const changes: ContainerSettings = {};
    for (const { key } of NUMBERS) if (Number.isFinite(parsed[key]) && parsed[key] !== current[key]) changes[key] = parsed[key];
    if ((cpuAlways === 'always') !== current.cpuAlways) changes.cpuAlways = cpuAlways === 'always';
    const save = async (container: ContainerSettings | null) => {
        setBusy(true);
        setErrors({});
        setFailure(undefined);
        try {
            await project.update({ container });
            invalidateV1('projects');
            const notes = Array.isArray(project.raw.notes) ? (project.raw.notes as string[]) : [];
            toast(notes.join(' ') || `Saved. ${APPLIES}`);
            onOpenChange(false);
        } catch (e) {
            const { message, field } = formError(e);
            const setting = container === null ? null : settingOf(field);
            if (setting) setErrors({ [setting]: message });
            else setFailure(e);
        } finally {
            setBusy(false);
        }
    };
    // Editing a setting puts its refusal away.
    const edit = (key: SettingKey) =>
        setErrors((was) => {
            const next = { ...was };
            delete next[key];
            return next;
        });
    return (
        <ConsoleDialog
            open={open}
            onOpenChange={onOpenChange}
            title="Container settings"
            description={`How each instance of ${project.name} runs in a container. ${APPLIES}`}
            footer={
                <>
                    {!isDefault(current) && (
                        <ConsoleButton disabled={busy} onClick={() => void save(null)}>
                            Reset to defaults
                        </ConsoleButton>
                    )}
                    <ConsoleButton variant="primary" disabled={busy || !valid || Object.keys(changes).length === 0} onClick={() => void save(changes)}>
                        {busy ? 'Saving…' : 'Save'}
                    </ConsoleButton>
                </>
            }
        >
            <form
                className="flex flex-col gap-4"
                onSubmit={(e) => {
                    e.preventDefault();
                    if (valid && Object.keys(changes).length) void save(changes);
                }}
            >
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                    {NUMBERS.map(({ key, label, hint, decimal }) => (
                        <FormField key={key} label={label} htmlFor={`container-${key}`} hint={hint} error={errors[key] ?? (text[key].trim() && !Number.isFinite(parsed[key]) ? 'A number, like 2.' : null)}>
                            <input
                                id={`container-${key}`}
                                className={cn(INPUT, 'tabular-nums')}
                                inputMode={decimal ? 'decimal' : 'numeric'}
                                value={text[key]}
                                aria-invalid={errors[key] ? true : undefined}
                                onChange={(e) => {
                                    setText((t) => ({ ...t, [key]: e.target.value }));
                                    edit(key);
                                }}
                                autoComplete="off"
                            />
                        </FormField>
                    ))}
                </div>
                <div className="flex flex-col gap-1">
                    <Choice
                        label="CPU between requests"
                        options={CPU_ALWAYS}
                        value={cpuAlways}
                        onChange={(next) => {
                            setCpuAlways(next);
                            edit('cpuAlways');
                        }}
                    />
                    {errors.cpuAlways && <p className="m-0 text-[12px] text-red-600 dark:text-red-400">{errors.cpuAlways}</p>}
                </div>
                {failure !== undefined && <ErrorPanel error={failure} />}
            </form>
        </ConsoleDialog>
    );
}

/** What each of the app's instances gets, and what its warm instances cost idle. */
export function AppContainer({ project }: { project: Project }) {
    const [editing, setEditing] = useState(false);
    const c = project.container;
    const note = c.note ?? (project.runtime === 'edge' ? ON_THE_EDGE : null);
    return (
        <Section
            title={
                <span className="flex items-center justify-between gap-2">
                    <span>Container</span>
                    <ConsoleButton size="sm" aria-label="Change container settings" onClick={() => setEditing(true)}>
                        Change
                    </ConsoleButton>
                </span>
            }
        >
            <p className="m-0 mb-1 text-[12px] text-muted-foreground">{APPLIES}</p>
            <dl aria-label="Container settings" className="m-0">
                <Field label="Each instance">
                    {plural(c.cpu, 'vCPU')}, {c.memory.toLocaleString('en-US')} MiB
                </Field>
                <Field label="Kept warm">{c.minInstances ? `${plural(c.minInstances, 'instance')}, while production serves it` : <span className="text-muted-foreground">None: one starts when a request comes</span>}</Field>
                <Field label="Most instances">{c.maxInstances}</Field>
                <Field label="CPU">{c.cpuAlways ? 'Always on: billed from start to stop' : 'Only during requests'}</Field>
                <Field label="Request timeout">{seconds(c.requestTimeoutS)}</Field>
                <Field label="Idle cost">{c.idleUsdPerMonth ? `${formatMoney(c.idleUsdPerMonth)} a month` : <span className="text-muted-foreground">Nothing with none kept warm</span>}</Field>
            </dl>
            {note && <p className="m-0 mt-1 text-[12px] text-muted-foreground">{note}</p>}
            <ContainerDialog project={project} open={editing} onOpenChange={setEditing} />
        </Section>
    );
}
