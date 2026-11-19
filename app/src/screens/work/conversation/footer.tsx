// Under a conversation's box, what it runs on, as New agent's draft has it: the account its model runs on (this
// conversation's, as the model picker sets it, by its kind: "Claude plan", the account itself in its tooltip and
// menu), where it runs, its budget (the agent's, through `agent.update`), and what triggers it, a dot between
// neighbours. On a laptop always one line: short of room, triggers fold to their marks first, then where it runs, its
// budget and last the account (`useFitRow`), each saying the rest in its tooltip. On a phone, where no tooltip opens,
// it's one line too, each pill whole and saying itself in a word ("Claude", "Sandbox", "$25/mo"), so the three fit a
// 360px screen; only the triggers' chips may run past its edge, reached by scrolling the line, softened where more waits.
// The Chat page draws it under its box for the account's NoClick: where it runs shown, not changed, on NoClick's own
// runtime; no triggers; its budget never uncapped.
// The account chip's menu also says what the agent does when a plan runs out (switch or stay, and between which).
// A change shows at once and holds from its next turn; one the platform refuses goes back, saying why.
import { useEffect, useRef, useState, type ReactNode } from 'react';
import { useInPhoneShell } from '@/ui/phoneBar';
import { cn } from '@/ui/utils';
import { toast } from 'sonner';
import { Agent, Machine, type ModelSwitching } from 'noclick';
import { invalidateV1 } from '@/sdk/useV1';
import { AGENTS_KEY, STATES_KEY } from '../agents/reads';
import { useWorkClient } from '../client';
import { AddComputer } from '../machine/AddComputer';
import { BuyMachine } from '../machine/BuyMachine';
import { useMachines } from '../machine/reads';
import { AccountChip, type AccountChipProps } from '../newAgent/AccountChip';
import { TriggersChip } from '../triggers/TriggersChip';
import { BudgetBody, budgetLabel, budgetShort, FOOT_ICONS, FOOT_ITEM, FootFact, FootPopover, NOT_ON_MACHINES, RunsBody, runsShort, runsText, type BudgetValue, type RunsValue } from '../newAgent/footer';
import { rereadAgent } from '../profile/reads';
import { SidewaysRow } from '../ui';
import { useFitRow } from './fitRow';

/** The order the row's items fold in when it's short of room: triggers first, the account last. */
const FOLDS = { triggers: 0, runs: 1, budget: 2, account: 3 } as const;


type Switching = Required<ModelSwitching>;
const same = (a: Switching, b: Switching) => JSON.stringify(a) === JSON.stringify(b);

/** What it does when a plan runs out, as the account chip's menu shows and changes it: what was picked shows at once,
 *  and the changes save one at a time (one made while another is on its way goes once that one lands, the latest of
 *  them only). A save the platform refuses goes back to what it last confirmed, saying why. */
function useSwitchingSave(agent: Agent): { value: Switching; onChange: (next: Switching) => void } {
    const client = useWorkClient();
    const saved = agent.modelSwitching;
    const [shown, setShown] = useState<Switching | null>(null);
    const confirmed = useRef(saved);
    // While a save is on its way: the latest change made meanwhile, sent after it.
    const flight = useRef<{ next: Switching | null } | null>(null);
    // The agent read again says what's saved, once nothing is on its way (a new object each read: compared by what it says).
    const savedKey = JSON.stringify(saved);
    useEffect(() => {
        if (flight.current) return;
        confirmed.current = saved;
        setShown(null);
        // eslint-disable-next-line react-hooks/exhaustive-deps -- `saved` is what `savedKey` says
    }, [savedKey]);
    const send = async (value: Switching): Promise<void> => {
        flight.current = { next: null };
        try {
            await Agent.fromId(agent.id, { client }).update({ modelSwitching: value });
            confirmed.current = value;
        } catch (error) {
            flight.current = null;
            setShown(confirmed.current);
            toast('Couldn’t change what it does when a plan runs out', { description: error instanceof Error ? error.message : String(error) });
            return;
        }
        const next = flight.current.next;
        flight.current = null;
        if (next && !same(next, value)) return send(next);
        rereadAgent(agent.id);
        invalidateV1(AGENTS_KEY);
    };
    return {
        value: shown ?? saved,
        onChange: (next) => {
            setShown(next);
            if (flight.current) flight.current.next = next;
            else void send(next);
        },
    };
}

/** Where `agent` runs as Runs in shows it: its machine by name, else its own sandbox. */
function runsOf(agent: Agent, machines: readonly Machine[] | undefined): RunsValue {
    if (!agent.machineId) return { kind: 'sandbox' };
    return { kind: 'machine', id: agent.machineId, name: machines?.find((m) => m.id === agent.machineId)?.name ?? 'Its machine' };
}

export function ConversationFooter({
    agent,
    chip,
    place,
    triggers = true,
    budgetUnset,
}: {
    agent: Agent;
    chip: AccountChipProps | null;
    /** Where it runs, shown and not changed here (the account's NoClick on NoClick's own runtime). */
    place?: { icon: ReactNode; text: string; tip: string; short?: string };
    /** Its triggers chip; the account's NoClick is reached the ways NoClick gives it. */
    triggers?: boolean;
    /** What no budget of its own comes to (the account's NoClick: its grant's cap), shown in place of No cap. */
    budgetUnset?: number;
}) {
    const client = useWorkClient();
    const phone = useInPhoneShell();
    const fit = useFitRow(!phone);
    const machines = useMachines();
    // What was just picked, shown until the agent read again says it.
    const [runs, setRuns] = useState<RunsValue | null>(null);
    const [budget, setBudget] = useState<{ value: BudgetValue } | null>(null);
    const [addingComputer, setAddingComputer] = useState(false);
    const [buyingMachine, setBuyingMachine] = useState(false);
    // Once the agent reads as changed, it says it itself.
    useEffect(() => setRuns(null), [agent.machineId]);
    useEffect(() => setBudget(null), [agent.budgetUsdPerMonth]);
    const switching = useSwitchingSave(agent);
    const shownRuns = runs ?? runsOf(agent, machines.data);
    const own = agent.budgetUsdPerMonth ?? budgetUnset ?? null;
    const shownBudget = budget ? budget.value : own;

    const update = async (changes: Parameters<Agent['update']>[0], what: string, undo: () => void) => {
        try {
            await Agent.fromId(agent.id, { client }).update(changes);
            rereadAgent(agent.id);
            invalidateV1(AGENTS_KEY);
            invalidateV1(STATES_KEY);
        } catch (error) {
            undo();
            toast(`Couldn’t change ${what}`, { description: error instanceof Error ? error.message : String(error) });
        }
    };
    const move = async (to: RunsValue) => {
        if (to.kind === 'sandbox' ? shownRuns.kind === 'sandbox' : shownRuns.kind === 'machine' && to.id === shownRuns.id) return;
        setRuns(to);
        const back = () => setRuns(null);
        if (to.kind === 'sandbox') return update({ machine: null }, 'where it runs', back);
        // The deployment may have turned machines off since Runs in was read.
        if (!(await Machine.agentsEnabledHere({ client }))) {
            back();
            return void toast(NOT_ON_MACHINES);
        }
        await update({ machine: to.id }, 'where it runs', back);
    };
    const saveBudget = (open: boolean) => {
        if (open || !budget || budget.value === own) return;
        void update({ budgetUsdPerMonth: budget.value }, 'its budget', () => setBudget(null));
    };

    const item = (fold: number) => ({ className: FOOT_ITEM, 'data-fold': fold, 'data-folded': fit.folded(fold) || undefined });
    return (
        // One line: a laptop's items fold to fit; a phone's scroll sideways, each whole (its padding holds their taps),
        // softened at either edge hiding more. Either way the row clips the first item's dot.
        <SidewaysRow enabled={phone} scrollRef={fit.row} data-testid="footer-row" className={cn('min-w-0', phone ? '-my-1.5 py-1.5' : 'overflow-x-clip [overflow-clip-margin:2px]')}>
            <div ref={fit.inner} className="flex w-max flex-nowrap items-center gap-x-2" data-testid="footer-strip">
                {chip && (
                    <span {...item(FOLDS.account)}>
                        <AccountChip {...chip} compact brief={phone} folded={fit.folded(FOLDS.account)} switching={switching} />
                    </span>
                )}
                <span {...item(FOLDS.runs)}>
                    {place ? (
                        <FootFact {...place} short={phone ? place.short : undefined} folded={fit.folded(FOLDS.runs)} />
                    ) : (
                        <FootPopover label="Runs in" icon={FOOT_ICONS.runs(shownRuns)} text={runsText(shownRuns)} short={phone ? runsShort(shownRuns) : undefined} width={340} folded={fit.folded(FOLDS.runs)}>
                            <RunsBody value={shownRuns} appTesting={agent.appTesting} onChange={(v) => void move(v)} onNewMachine={() => setBuyingMachine(true)} onAddComputer={() => setAddingComputer(true)} />
                        </FootPopover>
                    )}
                </span>
                <span {...item(FOLDS.budget)}>
                    <FootPopover label="Budget" icon={FOOT_ICONS.budget} text={budgetLabel(shownBudget)} short={phone ? budgetShort(shownBudget) : undefined} width={320} onOpenChange={saveBudget} folded={fit.folded(FOLDS.budget)}>
                        <BudgetBody value={shownBudget} onChange={(value) => setBudget({ value })} noCap={budgetUnset === undefined} />
                    </FootPopover>
                </span>
                {triggers && <TriggersChip agent={agent} className={FOOT_ITEM} fold={FOLDS.triggers} folded={fit.folded(FOLDS.triggers)} />}
            </div>
            {buyingMachine && <BuyMachine agent={{ name: agent.name, made: true }} onBought={(machine) => void move({ kind: 'machine', id: machine.id, name: machine.name })} onClose={() => setBuyingMachine(false)} />}
            {addingComputer && (
                <AddComputer
                    use={{
                        label: `Run ${agent.name} on it`,
                        onUse: (computer) => {
                            setAddingComputer(false);
                            void move({ kind: 'machine', id: computer.id, name: computer.name });
                        },
                    }}
                    onClose={() => setAddingComputer(false)}
                />
            )}
        </SidewaysRow>
    );
}
