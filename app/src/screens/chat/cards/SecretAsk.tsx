// A secret a message asks for (a space template's, which its agents read), as one ask's row: its values typed in
// right here, written straight into the account's secret and never shown again, to anyone. The account types them;
// anyone else sees it wait on the account. Filled (here, or anywhere NoClick reads it so), it's one line.
import { KeyRound } from 'lucide-react';
import { useState } from 'react';
import { Secret } from 'noclick';
import { useClient } from '@/sdk/client';
import { AskCard, AskMark, AskRow, PILL_PRIMARY, Receipt } from '@/ui/chat/primitives';
import { FIELD } from '@/ui/fields';
import { cn } from '@/ui/utils';

/** A value for each key, typed and never shown: what a secret or a file's keys take. Opened by a tap, so the first
 *  takes the focus. */
export function KeyFields({ keys, values, onChange }: { keys: readonly string[]; values: Record<string, string>; onChange: (next: Record<string, string>) => void }) {
    return (
        <>
            {keys.map((k, i) => (
                <label key={k} className="flex items-center gap-2">
                    <span className="w-[40%] min-w-0 truncate font-mono text-[12.5px] text-foreground/85">{k}</span>
                    <input type="password" autoComplete="off" autoFocus={i === 0} aria-label={k} value={values[k] ?? ''} onChange={(e) => onChange({ ...values, [k]: e.target.value })} className={cn(FIELD, 'h-9 flex-1 font-mono text-[13px]')} />
                </label>
            ))}
        </>
    );
}

export function SecretAsk({ id, name, keys, reason, state, mayAnswer }: { id: string; name: string; keys: readonly string[]; reason: string | null; state: string | null; mayAnswer: boolean }) {
    const client = useClient();
    const [entering, setEntering] = useState(false);
    const [values, setValues] = useState<Record<string, string>>({});
    const [saving, setSaving] = useState(false);
    const [saved, setSaved] = useState(false);
    const [failure, setFailure] = useState<string | null>(null);
    if (saved || state === 'succeeded') return <Receipt>Kept as {name}</Receipt>;
    const ready = keys.every((k) => values[k]?.trim());
    const save = async () => {
        setSaving(true);
        setFailure(null);
        try {
            await Secret.fromId(id, { client }).update(Object.fromEntries(keys.map((k) => [k, values[k]])));
            setSaved(true);
        } catch (e) {
            setFailure(e instanceof Error ? e.message : 'It couldn’t be kept.');
        } finally {
            setSaving(false);
        }
    };
    return (
        <div data-testid="secret-ask">
            <AskCard>
                <AskRow
                    wrap
                    lead={
                        <AskMark>
                            <KeyRound />
                        </AskMark>
                    }
                    title={name}
                    detail={[reason, mayAnswer ? 'never shown again' : 'the account adds it'].filter(Boolean).join(' · ')}
                    action={
                        mayAnswer && !entering ? (
                            <button type="button" className={PILL_PRIMARY} onClick={() => setEntering(true)}>
                                Enter
                            </button>
                        ) : undefined
                    }
                >
                    {mayAnswer && entering && (
                        <form
                            className="grid gap-2"
                            onSubmit={(e) => {
                                e.preventDefault();
                                if (ready) void save();
                            }}
                        >
                            <KeyFields keys={keys} values={values} onChange={setValues} />
                            <div className="pt-1">
                                <button type="submit" disabled={saving || !ready} className={PILL_PRIMARY}>
                                    Save
                                </button>
                            </div>
                        </form>
                    )}
                </AskRow>
            </AskCard>
            {failure && <p className="mt-2 text-[13px] text-red-600 dark:text-red-400">{failure}</p>}
        </div>
    );
}
