// What NoClick uses of a computer of yours, as one slider whose track is the split: the white is NoClick's part, the
// rest yours. It snaps to the parts in share.ts, names the one it's on and what that comes to once the computer
// reported its size, and saves when let go (after keys, a moment after the last press). In Add your computer it's set
// before the command runs (a Mac's VM is made that size); on the computer's page after, where a Mac's VM keeps it.
import { Check, Lock } from 'lucide-react';
import { useEffect, useId, useRef, useState } from 'react';
import { invalidateV1 } from '@/sdk/useV1';
import { NoClickError } from 'noclick';
import {
    setComputerShare,
    type OwnComputer,
} from '@/screens/resources/knowledge';
import { Section } from '@/screens/resources/ui';
import { reducedMotion, RollText, StopSlider, type SliderStop } from '@/ui/StopSlider';
import { cn } from '@/ui/utils';
import { useWorkClient } from '../client';
import { DEFAULT_SHARE, SHARES, shareLabel, splitOf } from './share';

const TITLE = 'What NoClick uses';
/** Each part sits at its share of the track, so the white is NoClick's part of the whole. */
const STOPS: readonly SliderStop<number>[] = SHARES.map((s) => ({ value: s.value, at: s.value }));

/** A share shown on its way to `target`, so the CPUs and memory count rather than jump. */
function useCount(target: number) {
    const [shown, setShown] = useState(target);
    const at = useRef(target);
    useEffect(() => {
        if (reducedMotion()) {
            at.current = target;
            setShown(target);
            return;
        }
        let frame = 0;
        const step = () => {
            const off = target - at.current;
            at.current =
                Math.abs(off) < 0.003 ? target : at.current + off * 0.17;
            setShown(at.current);
            if (at.current !== target) frame = requestAnimationFrame(step);
        };
        frame = requestAnimationFrame(step);
        return () => cancelAnimationFrame(frame);
    }, [target]);
    return shown;
}

const STATUS =
    'inline-flex items-center gap-1.5 justify-self-end whitespace-nowrap opacity-0 translate-y-[3px] [grid-area:1/1] [transition:opacity_.2s,transform_.25s_cubic-bezier(.25,1.25,.5,1)]';

/** Saving while a pick is on its way, then Saved for a moment. */
function SaveStatus({ saving, saved }: { saving: boolean; saved: boolean }) {
    return (
        <>
            <span
                aria-hidden
                data-testid="share-status"
                className="ml-auto grid text-[12.5px] font-normal text-muted-foreground"
            >
                <span
                    className={cn(
                        STATUS,
                        saving && 'translate-y-0 opacity-100'
                    )}
                >
                    <span className="h-1.5 w-1.5 animate-[pulse_.7s_ease-in-out_infinite_alternate] rounded-full bg-current" />
                    Saving
                </span>
                <span
                    className={cn(
                        STATUS,
                        !saving && saved && 'translate-y-0 opacity-100'
                    )}
                >
                    <Check className="h-3.5 w-3.5" strokeWidth={2} />
                    Saved
                </span>
            </span>
            <span
                className="sr-only"
                aria-live="polite"
                data-testid="share-saving"
            >
                {saving ? 'Saving' : saved ? 'Saved' : ''}
            </span>
        </>
    );
}

export interface ShareChoiceProps {
    computer: OwnComputer;
    /** Before it's installed, whether the command shown is a Mac's: its VM is made the size picked here. */
    mac?: boolean;
    /** The computer as the API answered a change. */
    onSaved?: (computer: OwnComputer) => void;
    /** On a page, as its own section: the page's heading, with the save state beside it. */
    section?: boolean;
}

export function ShareChoice({
    computer,
    mac = false,
    onSaved,
    section = false,
}: ShareChoiceProps) {
    const client = useWorkClient();
    const fixed = computer.agentShareFixed;
    const has = computer.agentShare ?? DEFAULT_SHARE;
    // The pick sent, shown until the computer as read says it; and one under a hand or keys, not sent yet.
    const [chosen, setChosen] = useState<number | null>(null);
    const [preview, setPreview] = useState<number | null>(null);
    const pick = preview ?? chosen ?? has;
    useEffect(() => {
        if (chosen !== null && computer.agentShare === chosen) setChosen(null);
    }, [chosen, computer.agentShare]);

    const [saving, setSaving] = useState(false);
    const [saved, setSaved] = useState(false);
    const [applied, setApplied] = useState(false);
    const [error, setError] = useState<{
        message: string;
        nextStep: string | null;
    } | null>(null);
    const [flash, setFlash] = useState(false);
    const token = useRef(0);
    useEffect(() => {
        if (!saved) return;
        const t = setTimeout(() => setSaved(false), 1600);
        return () => clearTimeout(t);
    }, [saved]);
    useEffect(() => {
        if (!flash) return;
        const t = setTimeout(() => setFlash(false), 900);
        return () => clearTimeout(t);
    }, [flash]);

    const count = useCount(pick);
    const vm = computer.pairing?.vm ?? null;
    const size =
        computer.cpu && computer.memoryGb
            ? { cpu: computer.cpu, gb: computer.memoryGb }
            : vm
              ? { cpu: vm.cpus, gb: vm.memoryGb }
              : null;
    const counting = !fixed && count !== pick;
    const split = size
        ? splitOf(size.cpu, size.gb, fixed ? pick : count, fixed, counting)
        : null;
    const exact = size ? splitOf(size.cpu, size.gb, pick, fixed) : null;

    const commit = async (value: number) => {
        setPreview(null);
        if (fixed || value === (chosen ?? has)) return;
        const prior = chosen;
        const t = ++token.current;
        setChosen(value);
        setSaving(true);
        setSaved(false);
        setApplied(false);
        setError(null);
        try {
            const next = await setComputerShare(client, computer.id, value);
            if (t !== token.current) return;
            invalidateV1(`machines/${computer.id}`);
            onSaved?.(next);
            setApplied(next.status === 'running');
            setSaved(true);
        } catch (e) {
            if (t !== token.current) return;
            setChosen(prior);
            setError({
                message: e instanceof Error ? e.message : String(e),
                nextStep: e instanceof NoClickError ? e.nextStep : null,
            });
        } finally {
            if (t === token.current) setSaving(false);
        }
    };

    const noteId = useId();
    const note = fixed
        ? 'NoClick’s VM on this Mac was made this size and keeps it: to change it, remove NoClick from the Mac and add it again.'
        : applied
          ? 'It takes this in a few seconds: agents already working keep going, and each takes its new size when it next starts.'
          : size
            ? null
            : mac
              ? 'On a Mac, NoClick’s VM is made this size when you run the command, and keeps it.'
              : 'A server just for NoClick: all of it. A computer you use: half or less, so it stays quick for you.';
    const status = <SaveStatus saving={saving} saved={saved} />;

    const body = (
        <div
            data-testid="share-choice"
            className="text-[12.5px] leading-[1.45]"
        >
            <div className="flex flex-wrap items-baseline justify-between gap-x-3 px-0.5 text-[13px] tabular-nums">
                <span className="inline-flex items-baseline whitespace-nowrap text-foreground">
                    <RollText order={pick} text={shareLabel(pick)} testId="share-stop" />
                    {split && (
                        <>
                            <span aria-hidden>&nbsp;·&nbsp;</span>
                            <span data-testid="share-noclick">
                                {split.noclick}
                            </span>
                        </>
                    )}
                </span>
                {split && (
                    <span
                        data-testid="share-you"
                        className="whitespace-nowrap text-muted-foreground"
                    >
                        You keep {split.you}
                    </span>
                )}
            </div>
            <StopSlider
                asShare
                stops={STOPS}
                value={pick}
                at={pick}
                onPreview={setPreview}
                onCommit={(value) => void commit(value)}
                label={TITLE}
                valueText={`${shareLabel(pick)}${exact ? `, ${exact.noclick.replace(' · ', ' and ')}` : ''}`}
                amount={(share) => share}
                describedBy={note ? noteId : undefined}
                locked={fixed}
                onRefused={() => setFlash(true)}
                knob={
                    fixed && (
                        <Lock
                            data-testid="share-locked"
                            className="h-3.5 w-3.5"
                            strokeWidth={2}
                        />
                    )
                }
                testId="share-track"
            />
            {split && computer.conversationsAtOnce ? (
                // The API's count is for the part it has; it fades while another is picked.
                <p
                    className={cn(
                        'mt-1 px-1 tabular-nums text-muted-foreground transition-opacity',
                        pick !== has && 'opacity-50'
                    )}
                >
                    Up to {computer.conversationsAtOnce}{' '}
                    {computer.conversationsAtOnce === 1
                        ? 'agent'
                        : 'agents'}{' '}
                    at once. What you keep stays yours, whatever the agents do.
                </p>
            ) : null}
            {note && (
                <p
                    id={noteId}
                    data-testid="share-note"
                    data-flash={flash || undefined}
                    className={cn(
                        'mt-2 px-1 leading-[1.4]',
                        flash
                            ? 'text-foreground'
                            : 'text-muted-foreground transition-colors duration-[350ms]'
                    )}
                >
                    {note}
                </p>
            )}
            {error && (
                <div
                    role="alert"
                    data-testid="share-error"
                    className="mt-2 px-1 leading-[1.4]"
                >
                    <p className="text-red-600 dark:text-red-400">
                        {error.message}
                    </p>
                    {error.nextStep && (
                        <p className="mt-0.5 text-muted-foreground">
                            {error.nextStep}
                        </p>
                    )}
                </div>
            )}
        </div>
    );

    if (section)
        return (
            <Section title={TITLE} action={status}>
                {body}
            </Section>
        );
    return (
        <div>
            <div className="mb-2 flex min-h-5 items-center gap-2.5">
                <p className="text-[13px] font-medium leading-5 text-foreground">
                    {TITLE}
                </p>
                {status}
            </div>
            {body}
        </div>
    );
}
