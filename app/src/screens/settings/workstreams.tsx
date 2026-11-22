// Settings → Workstreams: the lines of work the account's agents name as they start work, each with what it spent this
// month. A person renames one (a name another already has merges it there, which the dialog says before anything is
// sent), archives one whose work is done and unarchives it. `WorkstreamsView` draws what it's told;
// `WorkstreamsSection` is the section with its read (workstreamReads.ts). Changing one is the account's own call: the
// API refuses a call acting for one of its users.
import { useState, type FormEvent } from 'react';
import { GitMerge, Loader2, Pencil } from 'lucide-react';
import { money } from '@/screens/usage/derive';
import { BUTTON_GHOST, BUTTON_PRIMARY, BUTTON_SECONDARY } from '@/ui/buttons';
import { FIELD, FIELD_LABEL } from '@/ui/fields';
import { ShellDialog } from '@/ui/ShellDialog';
import { SettingsEmpty, SettingsGroup, SettingsGroupTitle, SettingsHeader, SettingsRow } from './parts';
import { useWorkstreams, type WorkstreamRow, type WorkstreamsState } from './workstreamReads';

/** The longest name the API keeps (`workstreams.service.MAX_NAME`). */
export const MAX_NAME = 60;

/** A name as the API keeps it: its words one space apart. */
const kept = (name: string) => name.split(/\s+/).filter(Boolean).join(' ');

/** What the API would refuse in a name, said before it's sent. */
export function nameError(name: string): string | null {
    if (!name) return 'Give it a name.';
    if (name.length > MAX_NAME) return `A name is at most ${MAX_NAME} characters.`;
    if (name.includes('/')) return 'A name can’t have a slash in it.';
    // eslint-disable-next-line no-control-regex
    if (/[\u0000-\u001f\u007f]/.test(name)) return 'A name is plain words.';
    return null;
}

const spentLine = (w: WorkstreamRow) => (w.spentUsd > 0 ? `${money(w.spentUsd)} this month` : 'Nothing spent this month');

const failure = (e: unknown, fallback: string) => (e instanceof Error && e.message ? e.message : fallback);

function Loading() {
    return (
        <SettingsGroup>
            {[0, 1, 2].map((k) => (
                <SettingsRow key={k} label={<span aria-label={k ? undefined : 'Loading your workstreams'} className="inline-block h-3.5 w-36 animate-pulse rounded bg-foreground/[0.06] align-middle" />} />
            ))}
        </SettingsGroup>
    );
}

export function WorkstreamsView({ state }: { state: WorkstreamsState }) {
    const { open, archived, error, retry } = state;
    const [renaming, setRenaming] = useState<WorkstreamRow | null>(null);
    // The one being archived or unarchived, and why the last change didn't go through.
    const [moving, setMoving] = useState<string | null>(null);
    const [refused, setRefused] = useState<string | null>(null);

    const move = async (w: WorkstreamRow, to: boolean) => {
        setMoving(w.id);
        setRefused(null);
        try {
            await state.setArchived(w.id, to);
        } catch (e) {
            setRefused(failure(e, to ? `${w.name} wasn’t archived.` : `${w.name} wasn’t unarchived.`));
        } finally {
            setMoving(null);
        }
    };

    const controls = (w: WorkstreamRow) => (
        <>
            <button type="button" onClick={() => setRenaming(w)} className={BUTTON_SECONDARY} aria-label={`Rename ${w.name}`}>
                Rename
            </button>
            <button type="button" onClick={() => void move(w, !w.archived)} disabled={moving === w.id} className={BUTTON_GHOST} aria-label={`${w.archived ? 'Unarchive' : 'Archive'} ${w.name}`}>
                {moving === w.id && <Loader2 className="h-4 w-4 animate-spin" />}
                {w.archived ? 'Unarchive' : 'Archive'}
            </button>
        </>
    );

    return (
        <div>
            <SettingsHeader title="Workstreams" description="The lines of work your agents name as they start, and what each spent this month." />
            {open === null || archived === null ? (
                error ? (
                    <SettingsGroup>
                        <SettingsRow
                            label="Your workstreams didn’t load."
                            description={<span role="alert">{error}</span>}
                            control={
                                <button type="button" onClick={retry} className={BUTTON_SECONDARY}>
                                    Try again
                                </button>
                            }
                        />
                    </SettingsGroup>
                ) : (
                    <Loading />
                )
            ) : (
                <div className="space-y-8">
                    <SettingsGroup note="Every charge of a workstream’s work, and of what it starts, is counted under it in Usage. An agent naming an archived one again brings it back.">
                        {open.length ? (
                            open.map((w) => <SettingsRow key={w.id} label={w.name} description={spentLine(w)} control={controls(w)} />)
                        ) : (
                            <SettingsEmpty>{archived.length ? 'Every workstream is archived.' : 'No workstreams yet. Your agents name one as they start work.'}</SettingsEmpty>
                        )}
                    </SettingsGroup>
                    {refused && (
                        <p role="alert" className="-mt-5 px-1 text-[13px] text-red-600 dark:text-red-400">
                            {refused}
                        </p>
                    )}
                    {archived.length > 0 && (
                        <div>
                            <SettingsGroupTitle title="Archived" description="Out of the workstreams your agents choose from. Their charges still read under them." />
                            <SettingsGroup>
                                {archived.map((w) => (
                                    <SettingsRow key={w.id} label={w.name} description={spentLine(w)} control={controls(w)} />
                                ))}
                            </SettingsGroup>
                        </div>
                    )}
                </div>
            )}
            {renaming && open && archived && (
                <RenameWorkstreamDialog
                    key={renaming.id}
                    workstream={renaming}
                    others={[...open, ...archived].filter((w) => w.id !== renaming.id)}
                    rename={state.rename}
                    onClose={() => setRenaming(null)}
                />
            )}
        </div>
    );
}

/** Renaming one: onto another's name (whatever its case) it merges there, which the dialog says first. */
export function RenameWorkstreamDialog({
    workstream,
    others,
    rename,
    onClose,
}: {
    workstream: WorkstreamRow;
    /** The account's other workstreams, open and archived. */
    others: WorkstreamRow[];
    rename: WorkstreamsState['rename'];
    onClose: () => void;
}) {
    const { id, name } = workstream;
    const [value, setValue] = useState(name);
    const [saving, setSaving] = useState(false);
    const [refused, setRefused] = useState<string | null>(null);

    const next = kept(value);
    const error = nameError(next);
    const into = others.find((w) => w.name.toLowerCase() === next.toLowerCase()) ?? null;
    const unchanged = next === name;
    const ready = !error && !unchanged && !saving;

    const submit = async (e: FormEvent<HTMLFormElement>) => {
        e.preventDefault();
        if (!ready) return;
        setSaving(true);
        setRefused(null);
        try {
            await rename(id, next);
            onClose();
        } catch (err) {
            setRefused(failure(err, 'It wasn’t renamed.'));
            setSaving(false);
        }
    };

    return (
        <ShellDialog
            open
            onOpenChange={(o) => !o && !saving && onClose()}
            title={into ? `Merge ${name} into ${into.name}?` : `Rename ${name}`}
            description={into ? 'A workstream of that name is already yours.' : 'Every charge it has, and every one to come, reads under its new name, here and in Usage.'}
            mark={into ? <GitMerge className="h-5 w-5" strokeWidth={1.75} /> : <Pencil className="h-5 w-5" strokeWidth={1.75} />}
            tone={into ? 'warning' : 'neutral'}
            testId="rename-workstream"
            onSubmit={(e) => void submit(e)}
            footer={
                <>
                    <button type="button" onClick={onClose} disabled={saving} className={BUTTON_GHOST}>
                        Cancel
                    </button>
                    <button type="submit" disabled={!ready} className={BUTTON_PRIMARY}>
                        {saving && <Loader2 className="h-4 w-4 animate-spin" />}
                        {into ? `Merge into ${into.name}` : 'Rename'}
                    </button>
                </>
            }
        >
            <div className="pb-1 pt-2">
                <label htmlFor="workstream-name" className={FIELD_LABEL}>
                    New name
                </label>
                <input
                    id="workstream-name"
                    autoFocus
                    value={value}
                    disabled={saving}
                    onChange={(e) => {
                        setValue(e.target.value);
                        setRefused(null);
                    }}
                    aria-invalid={!!error && !unchanged}
                    aria-describedby="workstream-name-note"
                    className={FIELD}
                />
                <div id="workstream-name-note" className="mt-2 text-[12.5px] leading-relaxed" aria-live="polite">
                    {error && value !== name ? (
                        <p className="text-red-600 dark:text-red-400">{error}</p>
                    ) : into ? (
                        <p className="text-muted-foreground">
                            Its charges so far, and every one to come, read as <span className="text-foreground">{into.name}</span>’s, and <span className="text-foreground">{name}</span> leaves your workstreams
                            {into.archived ? `; ${into.name} is unarchived` : ''}. A merge can’t be undone; no charge is rewritten.
                        </p>
                    ) : null}
                    {refused && (
                        <p role="alert" className="text-red-600 dark:text-red-400">
                            {refused}
                        </p>
                    )}
                </div>
            </div>
        </ShellDialog>
    );
}

/** The section with its read: the client and live frames its host hands it. */
export function WorkstreamsSection() {
    return <WorkstreamsView state={useWorkstreams()} />;
}
