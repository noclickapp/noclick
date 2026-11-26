// The owner's choice of what an agent does in a shared conversation (a channel several people, or an app's events,
// post in) when a call needs more than everyone there may do: Ask first (it cites the message that asked, else waits
// for you), Never (only what everyone may), or Allow (it needs nobody's word). Saved on the agent as its own approval
// setting `cited_authority` and read back; allowing it past the account's own setting is refused, saying so.
import { useState } from 'react';
import { toast } from 'sonner';
import { Agent } from 'noclick';
import { cn } from '@/ui/utils';
import { useWorkClient } from '../client';
import { nameOf } from '../agents/reads';
import { rereadAgent } from './reads';

type Choice = 'ask' | 'deny' | 'allow';

const KIND = 'cited_authority';
const CHOICES: readonly [Choice, string][] = [
    ['ask', 'Ask first'],
    ['deny', 'Never'],
    ['allow', 'Allow'],
];

function said(choice: Choice, name: string): string {
    if (choice === 'deny') return `${name} does only what everyone there may.`;
    if (choice === 'allow') return `${name} acts without anyone’s word. Only choose this for an agent you trust with everything it holds.`;
    return `${name} quotes the message that asked for it, from someone who may, and you see whose word it acted on. Without one, it waits for you.`;
}

/** The agent's own setting, as `approvals` reads it: a disposition, or one held in an entry. */
function current(agent: Agent): Choice {
    const entry = agent.approvals[KIND] as { disposition?: string } | string | undefined;
    const disposition = typeof entry === 'string' ? entry : entry?.disposition;
    return disposition === 'deny' || disposition === 'allow' ? disposition : 'ask';
}

export function CitedAuthoritySetting({ agent }: { agent: Agent }) {
    const client = useWorkClient();
    // The choice being saved, shown until the agent read again says it.
    const [saving, setSaving] = useState<Choice | null>(null);
    const name = nameOf(agent);
    const choice = saving ?? current(agent);
    const pick = async (next: Choice) => {
        if (next === choice) return;
        setSaving(next);
        try {
            await Agent.fromId(agent.id, { client }).update({ approvals: { [KIND]: next } });
            rereadAgent(agent.id);
        } catch (error) {
            toast('Couldn’t change it', { description: error instanceof Error ? error.message : String(error) });
        } finally {
            setSaving(null);
        }
    };
    return (
        <section className="mt-6" data-testid="agent-cited-authority">
            <h3 className="text-xs font-medium text-muted-foreground">Acting for others in shared conversations</h3>
            <p className="mt-1.5 text-[13px] leading-snug text-muted-foreground">
                Where several people (or an app’s events) talk to {name}, what it may do for each of them differs.
            </p>
            <div role="radiogroup" aria-label="Acting for others" className="mt-2.5 inline-flex rounded-full bg-foreground/[0.06] p-0.5">
                {CHOICES.map(([value, label]) => (
                    <button
                        key={value}
                        type="button"
                        role="radio"
                        aria-checked={choice === value}
                        disabled={saving !== null}
                        onClick={() => void pick(value)}
                        className={cn(
                            'h-7 whitespace-nowrap rounded-full px-3 text-[12.5px] transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-wait',
                            choice === value ? 'bg-popover font-medium text-foreground shadow-sm ring-1 ring-inset ring-border dark:ring-foreground/[0.12]' : 'text-muted-foreground hover:text-foreground'
                        )}
                    >
                        {label}
                    </button>
                ))}
            </div>
            <p className="mt-1.5 text-xs leading-snug text-muted-foreground">{said(choice, name)}</p>
        </section>
    );
}
