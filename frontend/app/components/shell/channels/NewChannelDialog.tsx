// Starting a channel: its name (kept as Slack keeps them: lowercase words and
// dashes), a one-line topic, whether agents answer every message or only
// their @-mentions, and which of your agents join: those in your Automations
// and your platform agents. In a workspace, a platform agent that isn't one of
// its members joins the workspace too.
import { useState, type FormEvent } from 'react';
import { Check, Hash } from 'lucide-react';
import { SegmentedControl } from '~/components/ui/segmented-control';
import { NodeMark } from '~/components/dashboard/primitives';
import { ShellDialog } from '~/components/shell/ShellDialog';
import { BUTTON_GHOST, BUTTON_PRIMARY } from '~/components/shell/buttons';
import { FIELD, FIELD_LABEL } from '~/components/shell/fields';
import { cn } from '~/lib/utils';
import { MemberAvatar } from './avatars';
import type { AccountMenuUser } from '~/components/nav/AccountMenu';
import { agentGroups, channelSlug, hueFor } from './model';
import type { AgentChoice, ChannelMode } from './types';

export interface NewChannelInput {
    name: string;
    topic: string;
    mode: ChannelMode;
    agents: AgentChoice[];
}

export function NewChannelDialog({
    open,
    onOpenChange,
    where,
    agents,
    agentsHref,
    user,
    onCreate,
}: {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    /** The workspace's name, for the title. */
    where: string;
    agents: AgentChoice[];
    agentsHref: string;
    user: AccountMenuUser;
    onCreate: (input: NewChannelInput) => Promise<void>;
}) {
    const [name, setName] = useState('');
    const [topic, setTopic] = useState('');
    const [mode, setMode] = useState<ChannelMode>('mentions');
    const [picked, setPicked] = useState<ReadonlySet<string>>(new Set());
    const [problem, setProblem] = useState<string | null>(null);
    const [busy, setBusy] = useState(false);
    const slug = channelSlug(name);

    const reset = () => {
        setName('');
        setTopic('');
        setMode('mentions');
        setPicked(new Set());
        setProblem(null);
    };
    const close = (next: boolean) => {
        if (busy) return;
        onOpenChange(next);
        if (!next) reset();
    };
    const toggle = (id: string) =>
        setPicked((prev) => {
            const next = new Set(prev);
            if (next.has(id)) next.delete(id);
            else next.add(id);
            return next;
        });

    const submit = async (e: FormEvent) => {
        e.preventDefault();
        if (!slug || busy) return;
        setBusy(true);
        setProblem(null);
        try {
            await onCreate({ name: slug, topic: topic.trim(), mode, agents: agents.filter((a) => picked.has(a.id)) });
            onOpenChange(false);
            reset();
        } catch (err) {
            setProblem(err instanceof Error ? err.message : 'Couldn’t start the channel.');
        } finally {
            setBusy(false);
        }
    };

    return (
        <ShellDialog
            open={open}
            onOpenChange={close}
            title="Start a channel"
            description={`In ${where}. Agents you add here answer in it.`}
            onSubmit={(e) => void submit(e)}
            testId="new-channel-dialog"
            footer={
                <>
                    <button type="button" onClick={() => close(false)} className={BUTTON_GHOST}>
                        Cancel
                    </button>
                    <button type="submit" disabled={!slug || busy} className={BUTTON_PRIMARY}>
                        {busy ? 'Starting…' : 'Start channel'}
                    </button>
                </>
            }
        >
            <div className="space-y-4 pt-2">
                <label className="block">
                    <span className={FIELD_LABEL}>Name</span>
                    <span className="relative block">
                        <Hash className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" strokeWidth={2} />
                        <input
                            // eslint-disable-next-line jsx-a11y/no-autofocus -- the dialog opens to name the channel
                            autoFocus
                            value={name}
                            onChange={(e) => setName(e.target.value)}
                            placeholder="launch-plans"
                            maxLength={80}
                            className={cn(FIELD, 'pl-9')}
                        />
                    </span>
                    {name.trim() && slug !== name.trim() && <span className="mt-1.5 block text-[12.5px] text-muted-foreground">Saved as #{slug || '…'}</span>}
                </label>
                <label className="block">
                    <span className={FIELD_LABEL}>Topic</span>
                    <input value={topic} onChange={(e) => setTopic(e.target.value)} placeholder="What it’s for, in a line" maxLength={250} className={FIELD} />
                </label>
                <div>
                    <span className={FIELD_LABEL}>Agents answer</span>
                    <SegmentedControl
                        className="w-full rounded-xl"
                        buttonClassName="h-9 flex-1 text-[13px]"
                        options={[
                            { value: 'mentions', label: 'When @-mentioned' },
                            { value: 'all', label: 'Every message' },
                        ]}
                        value={mode}
                        onChange={setMode}
                    />
                </div>
                <div>
                    <span className={FIELD_LABEL}>Agents</span>
                    {agents.length ? (
                        <div className="max-h-48 overflow-y-auto rounded-xl border border-border p-1 scrollbar-subtle dark:border-foreground/[0.1]">
                            {agentGroups(agents).map((group) => (
                                <section key={group.label} aria-label={group.label}>
                                    <p className="px-2 pb-0.5 pt-1.5 text-[11.5px] text-muted-foreground/80">{group.label}</p>
                                    <ul>
                                        {group.agents.map((agent) => {
                                            const on = picked.has(agent.id);
                                            return (
                                                <li key={agent.id}>
                                                    <button
                                                        type="button"
                                                        role="checkbox"
                                                        aria-checked={on}
                                                        onClick={() => toggle(agent.id)}
                                                        className="flex w-full items-center gap-3 rounded-lg px-2 py-1.5 text-left transition-colors hover:bg-foreground/[0.04]"
                                                    >
                                                        <MemberAvatar member={{ id: agent.id, kind: 'agent', name: agent.name, hue: hueFor(agent.id) }} user={user} size={24} />
                                                        <span className="min-w-0 flex-1 truncate text-[14px] text-foreground">
                                                            {agent.name}
                                                            {agent.source === 'automation' && <span className="text-muted-foreground"> · {agent.workflowName}</span>}
                                                        </span>
                                                        {agent.markType && <NodeMark type={agent.markType} size="xs" />}
                                                        <span className={cn('grid h-5 w-5 shrink-0 place-items-center rounded-md ring-1 ring-inset', on ? 'bg-primary text-primary-foreground ring-primary' : 'ring-border')}>
                                                            {on && <Check className="h-3.5 w-3.5" strokeWidth={2.5} />}
                                                        </span>
                                                    </button>
                                                </li>
                                            );
                                        })}
                                    </ul>
                                </section>
                            ))}
                        </div>
                    ) : (
                        <p className="text-[13px] leading-snug text-muted-foreground">
                            You have no agents yet.{' '}
                            <a href={agentsHref} className="font-medium text-foreground/80 underline decoration-foreground/25 underline-offset-[3px] hover:text-foreground">
                                Make one
                            </a>
                            , then add it here.
                        </p>
                    )}
                </div>
                {problem && (
                    <p role="alert" className="text-[12.5px] text-red-600 dark:text-red-400">
                        {problem}
                    </p>
                )}
            </div>
        </ShellDialog>
    );
}
