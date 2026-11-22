// An agent's triggers as Work reads and changes them: the list (its triggers and the one-off wake-ups it set itself),
// the names a sentence needs, each kind's mark, and every action (pause, resume, try it now, change, remove with Undo,
// cancel a wake-up, the fix a stopped one names), each saying what it did and reading the agent again.
import { useEffect, useMemo } from 'react';
import { toast } from 'sonner';
import { AlarmClock, AtSign, Bell, Clock, ListOrdered, Mail, Phone, ShieldCheck, Webhook, Workflow, Zap } from 'lucide-react';
import { Agent, Connection, Cron, OnEvent, OnPlatformEvent, OnQueue, OnWebhook, type TriggerChanges, type TriggerDefinition, type JsonObject } from 'noclick';
import { invalidateV1 } from '@/sdk/useV1';
import { useWork } from '../context';
import { cn } from '@/ui/utils';
import { errorText } from '@/screens/console/pages/resources/shared';
import { useWorkClient } from '../client';
import { STATES_KEY } from '../agents/reads';
import { rereadAgent, triggersKey, useTriggers, useWakeups } from '../profile/reads';
import { useWorkFrames } from '@/sdk/live';
import { AppMark, catalogApp, useEventApps, useEventFilters } from '../newAgent/wakes';
import { rereadAccounts, useConnections } from '../newAgent/catalog';
import { fixLabel, itemOf, sentenceOf, wakeupItem, type Names, type TriggerItem, type TriggerKind } from './model';
import { openTabForLater } from '@/lib/oauthPopup';
import { useSlot } from '@/slots';
import { CONNECT_APP } from '@/ui/slots';
import { connectionFor } from '@/lib/agentTools';

/** An account connected in the app, as a trigger names its connection: `credential:<id>`. */
const APP_REF = 'credential:';

/** The connection a trigger names, by its ref as the platform resolves it (an account connected in the app by its id,
 *  never by a name a named connection has). */
const connectionOf = (connections: readonly Connection[] | undefined, ref: string) => (connections ? connectionFor(ref, connections) : null);

/** Its triggers and the one-off wake-ups it set itself, as one list; `loading` until both are read. */
export function useTriggerItems(agentId: string, agentPaused: boolean): { items: TriggerItem[]; loading: boolean; error: boolean } {
    const triggers = useTriggers(agentId);
    const wakeups = useWakeups(agentId);
    const items = useMemo(
        () => [...(triggers.data ?? []).map((t) => itemOf(t, agentPaused)), ...(wakeups.data ?? []).filter((w) => w.at && !w.every).map((w) => wakeupItem(w, agentPaused))],
        [triggers.data, wakeups.data, agentPaused]
    );
    return { items, loading: !triggers.data && triggers.error === undefined, error: triggers.error !== undefined && !triggers.data };
}

/** Reads its triggers again as one fires and as the turn it started settles (a channel's busy agents come by its own
 *  frames), and as an account its app events hear through moves: reconnected from a Reconnect's popup, or its link
 *  found back up or down, since a trigger is stopped while its account isn't linked. */
export function useTriggerFrames(agentId: string): void {
    useWorkFrames('platform:resource', (frame) => {
        if ((frame.kind === 'trigger' && frame.parent_id === agentId) || frame.kind === 'connection') invalidateV1(triggersKey(agentId));
    });
    const { subscribe } = useSlot(CONNECT_APP);
    useEffect(() => subscribe?.(() => invalidateV1(triggersKey(agentId))), [subscribe, agentId]);
}

/** The names a sentence needs: an app event's app, from the connection it listens through. */
export function useTriggerNames(): Names {
    const connections = useConnections();
    const apps = useEventApps();
    return useMemo(
        () => ({
            appOf: (name: string) => {
                const connection = connectionOf(connections.data, name);
                const integration = connection?.integration ?? name;
                return apps.data?.find((a) => a.integration === integration)?.label ?? catalogApp(integration, connection?.credentialType ? [connection.credentialType] : []).label;
            },
        }),
        [connections.data, apps.data]
    );
}

/** The filters an app event takes (`about` says what each is, "Required." first where it needs one), and its
 *  description: from its integration's events, through the connection it listens on. */
export function useEventDetails(integration: string | undefined, event: string | undefined): { description: string; filters: { name: string; about: string; required: boolean }[] } | null {
    const events = useEventFilters(integration, event);
    const own = events.data?.find((e) => e.name === event);
    if (!own) return null;
    return {
        description: describeEvent(typeof own.description === 'string' ? own.description : ''),
        filters: Object.entries((own.filters ?? {}) as Record<string, string>).map(([name, about]) => ({ name, about: about.replace(/^required\.?\s*/i, ''), required: /^required\.?/i.test(about) })),
    };
}

/** A catalog event's description as a person reads it: no "Trigger:" lead, no schema boilerplate. */
export const describeEvent = (d: string) => {
    const t = d.replace(/^trigger:\s*/i, '').trim();
    return !t || /^configuration for/i.test(t) ? '' : t.charAt(0).toUpperCase() + t.slice(1);
};

/** The integration a connection belongs to. */
export function useIntegrationOf(): (connection: string) => string {
    const connections = useConnections();
    return (name) => connectionOf(connections.data, name)?.integration ?? name;
}

/** The node type that draws an app event's mark. */
export function useAppNodeType(): (connection: string) => string {
    const connections = useConnections();
    const apps = useEventApps();
    return (name) => {
        const connection = connectionOf(connections.data, name);
        const integration = connection?.integration ?? name;
        return apps.data?.find((a) => a.integration === integration)?.nodeType ?? catalogApp(integration).nodeType;
    };
}

const GLYPH: Record<Exclude<TriggerKind, 'event'>, typeof Clock> = {
    cron: Clock,
    routine: AlarmClock,
    wakeup: AlarmClock,
    webhook: Webhook,
    platform: Bell,
    queue: ListOrdered,
    email: Mail,
    call: Phone,
    channel: AtSign,
    approval: ShieldCheck,
    app: Workflow,
};

/** A trigger's mark: its app's for an app event (the one the platform names, else its connection's), else its kind's
 *  glyph. */
export function KindIcon({ item, kind, className = 'h-4 w-4' }: { item?: TriggerItem; kind?: TriggerKind; className?: string }) {
    const nodeType = useAppNodeType();
    const k = item?.kind ?? kind ?? 'event';
    if (k === 'event')
        return item ? (
            <AppMark nodeType={item.summary?.icon ?? nodeType(String(item.spec.connection ?? ''))} className={className} />
        ) : (
            <Zap className={cn('shrink-0 text-foreground/75', className)} strokeWidth={1.8} />
        );
    const Icon = GLYPH[k];
    return <Icon className={cn('shrink-0 text-foreground/75', className)} strokeWidth={1.8} />;
}

/** The definition a removed trigger is added back from (Undo). */
function definitionOf(item: TriggerItem): TriggerDefinition | null {
    const s = item.spec;
    const opt = (k: string) => (typeof s[k] === 'string' && s[k] ? (s[k] as string) : undefined);
    switch (item.kind) {
        case 'cron':
            return new Cron(String(s.cron), { tz: opt('tz'), message: opt('message') });
        case 'webhook':
            return new OnWebhook(String(s.name), { message: opt('message'), conversation: opt('conversation') });
        case 'event':
            return new OnEvent(String(s.connection), String(s.event), { filters: (s.filters ?? {}) as JsonObject, message: opt('message'), conversation: opt('conversation') });
        case 'platform':
            return new OnPlatformEvent(String(s.type), { filters: (s.filters ?? undefined) as JsonObject | undefined, message: opt('message'), conversation: opt('conversation') });
        case 'queue':
            return new OnQueue(String(s.queue), { message: opt('message') });
        default:
            return null;
    }
}

export interface TriggerActions {
    pause(item: TriggerItem): void;
    resume(item: TriggerItem): void;
    test(item: TriggerItem): void;
    remove(item: TriggerItem): void;
    update(item: TriggerItem, changes: TriggerChanges): Promise<boolean>;
    add(definition: TriggerDefinition): Promise<string | null>;
    /** The one thing that makes a stopped or paused one live again. */
    fix(item: TriggerItem): void;
    /** Pause or resume everything that wakes it. */
    setAgentPaused(paused: boolean): void;
    label(item: TriggerItem): string | null;
}

/** Every action on `agent`'s triggers; `onReplace` opens adding one in a stopped one's place. */
export function useTriggerActions(agent: Agent, names: Names, onReplace?: (item: TriggerItem) => void): TriggerActions {
    const client = useWorkClient();
    const { openWorkflowStep } = useWork();
    const connecting = useSlot(CONNECT_APP);
    const connections = useConnections();
    const it = () => Agent.fromId(agent.id, { client });
    const reread = () => {
        rereadAgent(agent.id);
        invalidateV1(STATES_KEY);
    };
    const run = async <T,>(what: string, call: () => Promise<T>, done?: (result: T) => void): Promise<boolean> => {
        try {
            const result = await call();
            reread();
            done?.(result);
            return true;
        } catch (error) {
            toast(`Couldn’t ${what}`, { description: errorText(error) });
            return false;
        }
    };
    const sentence = (item: TriggerItem) => sentenceOf(item, names);
    const actions: TriggerActions = {
        pause: (item) => void run('pause it', () => it().pauseTrigger(item.id), () => toast('Paused', { description: sentence(item) })),
        resume: (item) => void run('resume it', () => it().resumeTrigger(item.id), () => toast('Resumed', { description: sentence(item) })),
        test: (item) =>
            void run('try it', async () => {
                const op = await it().rehearseTrigger(item.id);
                toast('Trying it now', { description: 'A test run: its tools are answered by a stand-in, so nothing real happens.' });
                void op.wait().then(
                    (r) => toast(`What ${agent.name} would do`, { description: r.reply.length > 240 ? `${r.reply.slice(0, 237)}…` : r.reply || 'It had nothing to say.' }),
                    (error: unknown) => toast('The test run didn’t finish', { description: errorText(error) })
                );
            }),
        remove: (item) => {
            if (item.kind === 'wakeup' && item.wakeup) {
                const w = item.wakeup;
                void run('cancel it', () => w.cancel(), () => toast('Cancelled', { description: sentence(item) }));
                return;
            }
            const again = definitionOf(item);
            void run(
                'remove it',
                () => it().removeTrigger(item.id),
                () =>
                    toast('Removed', {
                        description: sentence(item),
                        ...(again && { action: { label: 'Undo', onClick: () => void run('put it back', () => it().addTrigger(again)) } }),
                    })
            );
        },
        update: (item, changes) => run('change it', () => it().updateTrigger(item.id, changes), () => toast('Changed', { description: sentence(item) })),
        add: async (definition) => {
            let made: string | null = null;
            await run('add it', () => it().addTrigger(definition), (t) => (made = t.id));
            return made;
        },
        fix: (item) => {
            const fix = item.fix;
            if (!fix) return;
            if (fix.action === 'resume_agent') return actions.setAgentPaused(false);
            if (fix.action === 'resume') return actions.resume(item);
            if (fix.action === 'open_in_app') {
                if (agent.workflowId && item.spec.step) openWorkflowStep?.(agent.workflowId, String(item.spec.step));
                return;
            }
            if (fix.action === 'replace') return onReplace?.(item);
            // An account connected in the app reconnects where it was connected (a WhatsApp phone: its code again).
            if (fix.connection?.startsWith(APP_REF)) {
                const credentialType = item.summary?.credentialType ?? connectionOf(connections.data, fix.connection)?.credentialType;
                if (credentialType) connecting.reconnect({ credentialType, credentialId: fix.connection.slice(APP_REF.length) }, client, names.appOf(fix.connection));
                return;
            }
            // Connect: its sign-in in a tab opened before the call, so the browser lets it open.
            const tab = openTabForLater();
            void (async () => {
                try {
                    const connection = await Connection.get(fix.connection ?? '', { client });
                    tab.go(connection.connectUrl ?? (await connection.request()).url);
                    rereadAccounts();
                } catch (error) {
                    tab.close();
                    toast(`Couldn’t reconnect ${names.appOf(fix.connection ?? '')}`, { description: errorText(error) });
                }
            })();
        },
        setAgentPaused: (paused) =>
            void run(paused ? 'pause its triggers' : 'resume its triggers', () => (paused ? it().pause() : it().resume()), () =>
                toast(paused ? 'Its triggers are paused' : 'Its triggers are back on', { description: paused ? 'Only messages and @mentions reach it.' : undefined })
            ),
        label: (item) => (item.fix ? fixLabel(item.fix, names) : null),
    };
    return actions;
}
