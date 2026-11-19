// The Chat page's switchers for the account's NoClick: Work's own, over the coordinator agent itself, whose model,
// harness, effort, account and budget are the person's (PATCH /v1/agents/{id}). The model picker beside Send offers
// every harness, as a new agent's does. Under the box: the account its model runs on (on NoClick's own runtime its
// key at cost unless one of yours is picked), where it runs (NoClick, on its own runtime; else Work's machine picker)
// and its budget (none set comes to its grant's $25). A move to a harness nothing of yours runs stays picked while
// the account chip asks to connect one, and is made once that account lands (a plan moving it to the plan's own
// harness, as the platform does); until then Send asks for that account, so nothing goes out on the model it still
// runs. What a move says back shows once under the box; a refusal goes back, saying why, but one for want of funds (a
// costly model on NoClick's key) opens Add funds, saying why that model needs them, and the move is made by itself
// once they land.
import { useMemo, useState, type ReactNode } from 'react';
import { Cloud } from 'lucide-react';
import { toast } from 'sonner';
import { InvalidRequest, type Agent, type NoClick } from 'noclick';
import { invalidateV1 } from '@/sdk/useV1';
import { coordinatorAgent } from '@/screens/work/coordinatorAgent';
import { useInPhoneShell } from '@/ui/phoneBar';
import { AGENTS_KEY } from '@/screens/work/agents/reads';
import { useConversationAccount } from '@/screens/work/conversation/account';
import { ConversationFooter } from '@/screens/work/conversation/footer';
import { useWorkFrames } from '@/sdk/live';
import { NOCLICK_KEY, planHarness } from '@/screens/work/newAgent/accounts';
import { useHarnesses, useModelAccounts } from '@/screens/work/newAgent/catalog';
import { ConnectSend } from '@/screens/work/newAgent/ConnectSend';
import { costlyModelOf, refusedForFunds, useFundsThenSwitch } from '@/screens/work/newAgent/funds';
import { HarnessModelPicker, PickerSheetHost, type PickerValue } from '@/screens/work/newAgent/ModelPicker';
import { rereadAgent, useAgent } from '@/screens/work/profile/reads';

/** What no budget of its own comes to: the cap on the grant its turns act as. */
export const GRANT_CAP_USD = 25;

const RUNS_ON_NOCLICK = {
    icon: <Cloud className="h-3.5 w-3.5" strokeWidth={1.75} />,
    text: 'Runs on NoClick',
    short: 'Cloud',
    tip: 'NoClick’s own agent always runs on NoClick’s servers. To pick where it runs, choose a coding agent like Claude Code or Codex beside Send.',
};

type Changes = Parameters<Agent['update']>[0];
/** A pick waiting on an account of yours to run it. */
type Pending = Pick<PickerValue, 'harness' | 'model' | 'effort' | 'speed' | 'permissions'>;

const reasonOf = (error: unknown) => (error instanceof Error && error.message ? error.message : 'NoClick couldn’t change it.');
// NoClick's key is no connection on its own runtime.
const connectionOf = (account: string | null, harness: string) => (account === NOCLICK_KEY && harness === 'sdk' ? null : account);

export interface ComposerControls {
    model: ReactNode;
    footer: ReactNode;
    /** Send while it can't run what's picked: the account it asks for, opened by Send and Enter alike. */
    ask: { button: ReactNode; open: () => void } | null;
}

/** The switchers, once the chat has found the agent (`found`); nothing before. Read inside Work's client and live
 *  frames. */
export function useCoordinatorComposerControls(client: NoClick, found: boolean): ComposerControls | undefined {
    const caller = useMemo(() => coordinatorAgent(client), [client]);
    const id = found && caller.isHydrated ? caller.id : null;
    // Shown from the chat's lookup at once, then as read again after each change.
    const agent = useAgent(id).data ?? (id ? caller : null);
    useWorkFrames('platform:coding_agent', (frame) => {
        if (id && frame.agent_id === id && frame.change === 'definition') rereadAgent(id);
    });
    const harnesses = useHarnesses();
    const { accounts } = useModelAccounts();
    const [pending, setPending] = useState<Pending | null>(null);
    // The pick waits on an account of yours (nothing was sent), not on a move under way.
    const [held, setHeld] = useState(false);
    const [notes, setNotes] = useState<string[]>([]);
    const [picker, setPicker] = useState(false);
    /** Makes `changes`, showing what the move says back. */
    const apply = async (changes: Changes) => {
        await caller.update(changes);
        setNotes(Array.isArray(caller.raw.notes) ? caller.raw.notes.map(String) : []);
        setPending(null);
        if (id) rereadAgent(id);
        invalidateV1(AGENTS_KEY);
    };
    // A move refused for want of funds opens Add funds, and is made by itself once they land.
    const adding = useFundsThenSwitch<Changes>(id ? `agent:${id}` : null, apply);
    // A phone opens the model and account pickers as sheets over the page, in a layer that's empty until one opens.
    const inPhone = useInPhoneShell();
    const [sheets, setSheets] = useState<HTMLElement | null>(null);
    const host = inPhone ? sheets : null;

    const harness = pending?.harness ?? agent?.harness ?? 'sdk';
    const info = harnesses.data?.find((h) => h.name === harness);
    const value: PickerValue | null = agent
        ? {
              ...(pending ?? {
                  harness,
                  model: agent.model ?? info?.defaultModel ?? '',
                  effort: agent.effort,
                  speed: info?.speeds.length ? agent.speed : null,
                  permissions: agent.permissionMode,
              }),
              account: pending ? null : agent.modelConnection,
          }
        : null;

    /** Makes `changes`, showing `shown` meanwhile; one the platform refuses for want of an account of yours stays
     *  picked (`shown`) for the account chip's Connect. */
    const move = async (changes: Changes, shown: Pending | null) => {
        setPending(shown);
        setHeld(false);
        setNotes([]);
        try {
            await apply(changes);
        } catch (error) {
            if (shown && error instanceof InvalidRequest && error.details.field === 'model_connection') return setHeld(true);
            setPending(null);
            if (refusedForFunds(error)) return adding.open(costlyModelOf(error), changes);
            toast('Couldn’t change it', { description: reasonOf(error) });
        }
    };

    const pick = (next: PickerValue) => {
        if (!value) return;
        const changes: Changes = {};
        if (next.harness !== value.harness) changes.harness = next.harness;
        if (next.model !== value.model) changes.model = next.model;
        if (next.effort !== value.effort && next.effort) changes.effort = next.effort;
        if (next.speed !== value.speed && next.speed) changes.speed = next.speed as 'standard' | 'fast';
        if (next.permissions !== value.permissions && next.harness !== 'sdk') changes.permissionMode = next.permissions;
        const account = next.account ?? null;
        if (changes.harness || account !== (value.account ?? null)) changes.modelConnection = connectionOf(account, next.harness);
        if (!Object.keys(changes).length) return;
        const shown: Pending = { harness: next.harness, model: next.model, effort: next.effort, speed: next.speed, permissions: next.permissions };
        // Nothing of yours runs it: no move to refuse yet, only the pick, for the account chip to ask for one.
        if (next.harness !== 'sdk' && !account) {
            setNotes([]);
            setHeld(true);
            return setPending(shown);
        }
        void move(changes, changes.harness ? shown : null);
    };

    /** An account picked or just connected: it runs the pick, or moves it to a plan's own harness. */
    const takeAccount = (landed: string) => {
        if (!value) return;
        const account = accounts?.find((a) => a.id === landed);
        const to = account ? planHarness(account, value.harness) : null;
        const changes: Changes = to
            ? { harness: to }
            : pending
              ? { harness: pending.harness, model: pending.model, ...(pending.effort ? { effort: pending.effort } : {}) }
              : {};
        void move({ ...changes, modelConnection: connectionOf(landed, to ?? value.harness) }, to ? null : pending);
    };
    const account = useConversationAccount({ harness: value?.harness ?? null, model: value?.model ?? null, connection: value?.account ?? null }, takeAccount, () => id && rereadAgent(id));
    // A held pick asks for an account that runs it; else the one it runs on, once its provider refused it.
    const ask = held && pending ? (account.chip?.ask ?? null) : account.ask;

    if (!agent || !value) return undefined;
    return {
        model: (
            <PickerSheetHost.Provider value={host}>
                <HarnessModelPicker value={value} onChange={pick} accounts={accounts} open={picker} onOpenChange={setPicker} accountInPill={false} fundsOwner={id ? `agent:${id}` : undefined} />
            </PickerSheetHost.Provider>
        ),
        footer: (
            <PickerSheetHost.Provider value={host}>
                <div className="mt-1.5 px-1.5" data-testid="coordinator-composer-footer">
                    <ConversationFooter agent={agent} chip={account.chip} place={harness === 'sdk' ? RUNS_ON_NOCLICK : undefined} triggers={false} budgetUnset={GRANT_CAP_USD} />
                    {notes.map((note) => (
                        <p key={note} className="px-2 pt-1 text-[12px] leading-snug text-muted-foreground" data-testid="coordinator-move-note">
                            {note}
                        </p>
                    ))}
                    {account.dialog}
                    {adding.dialog}
                </div>
                {inPhone && <div ref={setSheets} className="pointer-events-none fixed inset-0 z-50 [&>*]:pointer-events-auto" />}
            </PickerSheetHost.Provider>
        ),
        ask: ask ? { button: <ConnectSend ask={ask} onClick={() => account.reconnect()} />, open: () => account.reconnect() } : null,
    };
}
