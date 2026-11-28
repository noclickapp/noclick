// A new agent's Draft, in its conversation's place (t3's empty-draft screen): "What should a new agent do?", one box
// for its job (pictures and PDFs go with it), the shared harness and model picker set from the job and the account's
// AI accounts until the person picks, then the account it runs on, where it runs and its budget, each changeable in
// place. With no account that runs the pick, Send asks for one and opens the app's own connect popup. Send makes the
// agent (POST /v1/agents; it wakes on messages and @-mentions), puts it in the space, and posts the job as its first
// message. Or a session moves in from a laptop.
import { useEffect, useMemo, useRef, useState } from 'react';
import { toast } from 'sonner';
import { ArrowUp, FileText, Paperclip, X } from 'lucide-react';
import { Agent, Machine, NotAvailable, type Attachment, type HarnessInfo } from 'noclick';
import { invalidateV1 } from '@/sdk/useV1';
import { ShortcutTooltip } from '@/ui/ShortcutTooltip';
import { useInPhoneShell } from '@/ui/phoneBar';
import { cn } from '@/ui/utils';
import { useWorkClient } from '../client';
import { DisabledTip } from '../tooltip';
import { SidewaysRow } from '../ui';
import { AGENTS_KEY, STATES_KEY, useAgents } from '../agents/reads';
import { WorkMotion } from '../agents/AgentRing';
import { harnessName } from '../agents/harness';
import { AccountChip } from './AccountChip';
import { ConnectSend } from './ConnectSend';
import { accountPayer, connectAsk, firstUsable, NOCLICK_KEY, routeFor, waysFor } from './accounts';
import { useHarnesses, useModelAccounts, useModelRoutes } from './catalog';
import { BudgetBody, budgetLabel, budgetShort, FOOT_ICONS, FOOT_ITEM, FOOT_ROW, FootPopover, NEW_APP_TESTING, NEW_BUDGET, NOT_ON_MACHINES, RunsBody, runsShort, runsText, type BudgetValue, type RunsValue } from './footer';
import { costlyModelOf, refusedForFunds, useAddFunds } from './funds';
import { harnessFor, nameFor } from './infer';
import { HarnessModelPicker, newPickerValue, PickerSheetHost, useConnectAi, useModelLabel, type PickerValue } from './ModelPicker';
import { AddComputer } from '../machine/AddComputer';
import { BuyMachine } from '../machine/BuyMachine';
import { answerNotes } from '../machine/machineView';
import { MoveCard } from './move';

export interface NewAgentProps {
    spaceId: string | null;
    onCreated(agentId: string): void;
    onCancel(): void;
}

interface Chip {
    id: string;
    file: File;
    thumb: string | null;
}

/** A picture or PDF going with its first message: its thumbnail or a file mark, its name, and a way to take it out. */
function DraftChip({ chip, onRemove }: { chip: Chip; onRemove: () => void }) {
    return (
        <span className="inline-flex h-7 max-w-[300px] items-center gap-1.5 rounded-full bg-foreground/[0.05] pl-1.5 pr-0.5 text-xs text-foreground/85 ring-1 ring-inset ring-foreground/[0.06]">
            {chip.thumb ? (
                <img src={chip.thumb} alt="" className="h-5 w-5 shrink-0 rounded-full object-cover" />
            ) : (
                <span className="pl-0.5">
                    <FileText className="h-3.5 w-3.5 shrink-0 text-muted-foreground" strokeWidth={2} />
                </span>
            )}
            <span className="truncate">{chip.file.name}</span>
            <button type="button" aria-label={`Remove ${chip.file.name}`} onClick={onRemove} className="grid h-6 w-6 shrink-0 place-items-center rounded-full text-muted-foreground transition-colors hover:bg-foreground/[0.08] hover:text-foreground">
                <X className="h-3 w-3" strokeWidth={2.25} />
            </button>
        </span>
    );
}

/** Below 640px the picker opens as a bottom sheet over the draft. */
function useNarrow() {
    const [narrow, setNarrow] = useState(false);
    useEffect(() => {
        const query = window.matchMedia('(max-width: 639px)');
        const update = () => setNarrow(query.matches);
        update();
        query.addEventListener('change', update);
        return () => query.removeEventListener('change', update);
    }, []);
    return narrow;
}

let chipSeq = 0;

export function NewAgent({ spaceId, onCreated, onCancel }: NewAgentProps) {
    const client = useWorkClient();
    const harnesses = useHarnesses();
    const { accounts, labels } = useModelAccounts();
    // On a phone its pills keep one line, scrolling sideways inside it, as a conversation's do.
    const phone = useInPhoneShell();
    const agents = useAgents();
    const [job, setJob] = useState('');
    const [picked, setPicked] = useState<PickerValue | null>(null);
    // The account the person chose themselves (in the menu, or by connecting it here), as the menu says why it's used.
    const [chosen, setChosen] = useState<string | null>(null);
    const [runs, setRuns] = useState<RunsValue>({ kind: 'sandbox' });
    const [budget, setBudget] = useState<BudgetValue>(NEW_BUDGET);
    const [chips, setChips] = useState<Chip[]>([]);
    const [dragging, setDragging] = useState(false);
    const [sending, setSending] = useState(false);
    const [addingComputer, setAddingComputer] = useState(false);
    const [buyingMachine, setBuyingMachine] = useState(false);
    const fileInput = useRef<HTMLInputElement>(null);
    const box = useRef<HTMLTextAreaElement>(null);
    const narrow = useNarrow();
    const [sheet, setSheet] = useState<HTMLElement | null>(null);
    useEffect(() => box.current?.focus(), []);

    const taken = useMemo(() => (agents.data ?? []).map((a) => a.name), [agents.data]);
    const name = nameFor(job, taken);

    // The picker opens on what NoClick inferred and follows the job, until the person picks. Its account is the one
    // that runs the model: the picked one while it does, else the first that does.
    const held = useMemo(() => accounts ?? [], [accounts]);
    const harnessOf = (n: string) => harnesses.data?.find((h) => h.name === n);
    const inferredHarness: HarnessInfo | undefined = harnessOf(picked?.harness ?? harnessFor(job, held)) ?? harnessOf('sdk');
    const base: PickerValue | null = inferredHarness ? (picked ?? newPickerValue(inferredHarness)) : null;
    // On NoClick's key a coding harness runs the models it suggests.
    // One model reached several ways (its maker, OpenRouter, Zen): the account decides the way.
    const { routes, free } = useModelRoutes(inferredHarness, base?.model ?? '');
    const account = inferredHarness && base ? firstUsable(held, inferredHarness, routes, picked?.account) : null;
    const value: PickerValue | null = base && inferredHarness ? { ...base, model: !picked && account?.id === NOCLICK_KEY && inferredHarness.noclickKey.models[0] ? inferredHarness.noclickKey.models[0] : base.model, account: account?.id ?? null } : null;
    // A free model of Zen's own tier runs with no account, where none of yours runs the pick.
    const keyless = !account && free ? free : null;
    const blocked = !!value && !account && !keyless;
    // An account connected from here is picked once it's read: the pick as it is then, on that account.
    const connecting = useConnectAi((id) => {
        if (!value) return;
        setPicked({ ...value, account: id });
        setChosen(id);
    });
    // Making it on a costly model on NoClick's key the account hasn't the funds for: Add funds, rather than a refusal.
    const adding = useAddFunds();
    // The ways that run the pick, and what Send asks for while none of yours does.
    const pickModel = value?.model;
    const ways = useMemo(() => (inferredHarness && pickModel ? waysFor(inferredHarness, pickModel, labels, routes) : []), [inferredHarness, pickModel, labels, routes]);
    const ask = inferredHarness && value ? connectAsk(held, inferredHarness, value.model, ways, routes) : null;
    const modelLabel = useModelLabel(inferredHarness, value?.model ?? '');
    // What keeps it from being made, said on Send; null when it can be.
    const why = !value ? 'Reading the models' : blocked && ask ? ask.send : !job.trim() ? 'Write its job first' : null;

    const attach = (files: FileList | File[]) => {
        const added: Chip[] = [];
        for (const f of Array.from(files)) {
            if (f.type.startsWith('image/')) added.push({ id: `chip-${++chipSeq}`, file: f, thumb: URL.createObjectURL(f) });
            else if (f.type === 'application/pdf') added.push({ id: `chip-${++chipSeq}`, file: f, thumb: null });
            else toast(`${f.name} isn’t a picture or a PDF`, { description: 'Those go with its first message as they are. Put other files in its files once it’s made.' });
        }
        if (added.length) setChips((prev) => [...prev, ...added]);
    };

    const send = async () => {
        if (why || !value || sending) return;
        setSending(true);
        let made: Agent | null = null;
        try {
            // The deployment may have turned machines off since Runs in was read: say so before anything is made.
            if (runs.kind !== 'sandbox' && !(await Machine.agentsEnabledHere({ client }))) {
                toast(NOT_ON_MACHINES);
                return;
            }
            const machine = runs.kind === 'machine' ? runs.id : undefined;
            made = await Agent.create(name, {
                client,
                instructions: job.trim(),
                harness: value.harness,
                // The way to the model its account takes; a free Zen model's own, with no account.
                model: (account && inferredHarness && routeFor(account, inferredHarness, routes)) || keyless?.id || value.model,
                ...(value.account && !(value.harness === 'sdk' && value.account === NOCLICK_KEY) ? { modelConnection: value.account } : {}),
                ...(value.effort ? { effort: value.effort } : {}),
                ...(value.speed && value.speed !== 'standard' ? { speed: value.speed as 'fast' } : {}),
                budgetUsdPerMonth: budget,
                ...(value.permissions !== 'full-access' ? { permissionMode: value.permissions } : {}),
                ...(machine ? { machine } : {}),
                // It joins the space it's made in.
                ...(spaceId ? { workspace: spaceId } : {}),
            });
            const agent = made;
            // On a machine on its owner's plan, its creation says where the plan's sign-in is kept.
            const notes = machine ? answerNotes(agent.raw) : [];
            const files: Attachment[] = [];
            for (const chip of chips) files.push(await agent.upload(chip.file));
            await agent.send(job.trim(), { files });
            invalidateV1(AGENTS_KEY);
            invalidateV1(STATES_KEY);
            toast(`${agent.name} is ready`, { description: [`${harnessName(value.harness)} · ${account ? accountPayer(account) : ''}`, ...notes].join('. ') });
            onCreated(agent.id);
        } catch (error) {
            const why = error instanceof Error ? error.message : String(error);
            if (made) {
                // It exists: open it, and say what didn't finish.
                invalidateV1(AGENTS_KEY);
                invalidateV1(STATES_KEY);
                toast(`${made.name} is made, but not all of it went through`, { description: why });
                onCreated(made.id);
            } else if (refusedForFunds(error)) adding.open(costlyModelOf(error));
            else if (error instanceof NotAvailable) toast(why);
            else toast('Couldn’t make the agent', { description: why });
        } finally {
            setSending(false);
        }
    };

    return (
        <div ref={setSheet} className="relative flex min-h-0 flex-1 flex-col items-center overflow-y-auto px-6 py-8 max-sm:px-4" data-testid="new-agent">
            <WorkMotion />
            <PickerSheetHost.Provider value={narrow ? sheet : null}>
                <div className="my-auto w-full max-w-[46rem] pb-[8vh] max-sm:pb-4">
                    <h1 className="text-center text-2xl font-normal tracking-tight text-foreground sm:text-3xl">What should a new agent do?</h1>
                    <div
                        className={cn('mt-7 rounded-[26px] bg-composer px-4 pb-2.5 pt-3.5 shadow-[0_18px_48px_-24px_rgba(0,0,0,0.35)] ring-1 ring-inset ring-border dark:ring-foreground/[0.09]', dragging && 'ring-2 ring-foreground/30 dark:ring-foreground/30')}
                        onDragOver={(e) => {
                            if (!e.dataTransfer.types.includes('Files')) return;
                            e.preventDefault();
                            setDragging(true);
                        }}
                        onDragLeave={() => setDragging(false)}
                        onDrop={(e) => {
                            if (!e.dataTransfer.files.length) return;
                            e.preventDefault();
                            setDragging(false);
                            attach(e.dataTransfer.files);
                        }}
                    >
                        {chips.length > 0 && (
                            <div className="mb-2 flex flex-wrap gap-1.5">
                                {chips.map((c) => (
                                    <DraftChip key={c.id} chip={c} onRemove={() => setChips((prev) => prev.filter((x) => x.id !== c.id))} />
                                ))}
                            </div>
                        )}
                        <textarea
                            ref={box}
                            value={job}
                            onChange={(e) => setJob(e.target.value)}
                            onPaste={(e) => {
                                if (!e.clipboardData.files.length) return;
                                e.preventDefault();
                                attach(e.clipboardData.files);
                            }}
                            onKeyDown={(e) => {
                                if (e.key === 'Enter' && !e.shiftKey) {
                                    e.preventDefault();
                                    void send();
                                }
                                if (e.key === 'Escape') onCancel();
                            }}
                            rows={2}
                            aria-label="Its job"
                            placeholder="Describe its job. It reads this as its first message."
                            className="block w-full resize-none bg-transparent text-[14px] leading-relaxed text-foreground outline-none placeholder:text-[hsl(var(--placeholder))] max-sm:text-[16px]"
                        />
                        <div className="mt-1.5 flex items-center gap-1">
                            <ShortcutTooltip label="Pictures and PDFs (or paste, or drop them here)">
                                <button
                                    type="button"
                                    onClick={() => fileInput.current?.click()}
                                    aria-label="Attach pictures or PDFs"
                                    className="grid h-8 w-8 shrink-0 place-items-center rounded-full text-muted-foreground transition-colors hover:bg-foreground/[0.06] hover:text-foreground"
                                >
                                    <Paperclip className="h-4 w-4" strokeWidth={1.75} />
                                </button>
                            </ShortcutTooltip>
                            <input
                                ref={fileInput}
                                type="file"
                                accept="image/*,application/pdf"
                                multiple
                                hidden
                                aria-label="Pictures or PDFs to attach"
                                onChange={(e) => {
                                    if (e.target.files) attach(e.target.files);
                                    e.target.value = '';
                                }}
                            />
                            <span className="ml-auto" />
                            {value && <HarnessModelPicker value={value} onChange={setPicked} fundsOwner="new-agent" />}
                            {blocked && ask && inferredHarness && value ? (
                                <ConnectSend ask={ask} onClick={() => connecting.connect(inferredHarness, value.model)} />
                            ) : (
                            <DisabledTip label={why} disabled={!!why || sending} side="top">
                                <button
                                    type="button"
                                    disabled={!!why || sending}
                                    onClick={() => void send()}
                                    aria-label="Make it and send"
                                    className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-foreground text-background transition-[opacity,transform] duration-150 active:scale-95 disabled:opacity-25"
                                >
                                    {sending ? <span aria-hidden className="work-spin h-3.5 w-3.5 rounded-full border-2 border-background/30 border-t-background" /> : <ArrowUp className="h-4 w-4" strokeWidth={2.25} />}
                                </button>
                            </DisabledTip>
                            )}
                        </div>
                    </div>
                    <div className="mt-1.5 px-1.5">
                        <SidewaysRow enabled={phone} className={cn(FOOT_ROW, phone && '-my-1.5 flex-nowrap py-1.5 [&>*]:shrink-0')}>
                            {inferredHarness && value && ask && (
                                <span className={FOOT_ITEM}>
                                    <AccountChip
                                        harness={inferredHarness}
                                        model={value.model}
                                        modelLabel={modelLabel}
                                        accounts={held}
                                        account={account}
                                        routes={routes}
                                        free={keyless?.name ?? null}
                                        picked={!!account && chosen === account.id}
                                        ask={ask}
                                        ways={ways}
                                        onPick={(id) => {
                                            setPicked({ ...value, account: id });
                                            setChosen(id);
                                        }}
                                        onConnect={(another) => connecting.connect(inferredHarness, value.model, { another })}
                                        brief={phone}
                                    />
                                </span>
                            )}
                            <span className={FOOT_ITEM}>
                                <FootPopover label="Runs in" icon={FOOT_ICONS.runs(runs)} text={runsText(runs)} short={phone ? runsShort(runs) : undefined} width={340}>
                                    <RunsBody value={runs} appTesting={NEW_APP_TESTING} onChange={setRuns} onNewMachine={() => setBuyingMachine(true)} onAddComputer={() => setAddingComputer(true)} />
                                </FootPopover>
                            </span>
                            <span className={FOOT_ITEM}>
                                <FootPopover label="Budget" icon={FOOT_ICONS.budget} text={budgetLabel(budget)} short={phone ? budgetShort(budget) : undefined} width={320}>
                                    <BudgetBody value={budget} onChange={setBudget} />
                                </FootPopover>
                            </span>
                        </SidewaysRow>
                    </div>
                    {connecting.dialog}
                    {adding.dialog}
                    {buyingMachine && <BuyMachine agent={{ name, made: false }} onBought={(machine) => setRuns({ kind: 'machine', id: machine.id, name: machine.name })} onClose={() => setBuyingMachine(false)} />}
                    {addingComputer && (
                        <AddComputer
                            use={{
                                label: 'Use it for this agent',
                                onUse: (computer) => {
                                    setRuns({ kind: 'machine', id: computer.id, name: computer.name });
                                    setAddingComputer(false);
                                },
                            }}
                            onClose={() => setAddingComputer(false)}
                        />
                    )}
                    <div className="mt-8 flex flex-col items-center gap-3">
                        <span className="flex w-full max-w-[30rem] items-center gap-3 text-[12px] text-muted-foreground max-sm:max-w-none" aria-hidden>
                            <span className="h-px flex-1 bg-border dark:bg-foreground/[0.08]" />
                            or
                            <span className="h-px flex-1 bg-border dark:bg-foreground/[0.08]" />
                        </span>
                        <MoveCard
                            spaceId={spaceId}
                            machineId={runs.kind === 'machine' ? runs.id : null}
                            onMoved={(agentId) => {
                                invalidateV1(AGENTS_KEY);
                                invalidateV1(STATES_KEY);
                                onCreated(agentId);
                            }}
                        />
                    </div>
                </div>
            </PickerSheetHost.Provider>
        </div>
    );
}
