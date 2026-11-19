// The owner's choice of how a coding agent may turn app testing on (Docker in its sandbox, for a task that runs the app
// or its tests against a real database): By itself, Ask first or Never, saved on the agent (`app_testing`) and read
// back. The chat says each switch; this is where its owner changes what the agent may do, at the price an hour of it
// costs where it runs. On a machine the machine's own choice bounds it (the stricter holds), at no extra cost; an agent
// with Docker always on shows that instead.
import { useState } from 'react';
import { toast } from 'sonner';
import { Agent, type AppTesting } from 'noclick';
import { cn } from '@/ui/utils';
import { useWorkClient } from '../client';
import { nameOf } from '../agents/reads';
import { rereadAgent } from './reads';

const MODES: readonly [AppTesting, string][] = [
    ['by_itself', 'By itself'],
    ['ask_first', 'Ask first'],
    ['never', 'Never'],
];

function modeSaid(mode: AppTesting, name: string): string {
    if (mode === 'ask_first') return `${name} asks you in the chat each time a task needs it.`;
    if (mode === 'never') return `${name} checks code without running it.`;
    return `${name} turns it on when a task needs it, off as soon as it’s done, and says so in the chat.`;
}

export function AppTestingSetting({ agent }: { agent: Agent }) {
    const client = useWorkClient();
    // The choice being saved, shown until the agent read again says it.
    const [saving, setSaving] = useState<AppTesting | null>(null);
    if (!agent.harness || agent.harness === 'sdk') return null;
    const name = nameOf(agent);
    const mode = saving ?? agent.appTesting;
    const hourly = agent.appTestingUsdPerHour;
    const pick = async (next: AppTesting) => {
        if (next === mode) return;
        setSaving(next);
        try {
            await Agent.fromId(agent.id, { client }).update({ appTesting: next });
            rereadAgent(agent.id);
        } catch (error) {
            toast('Couldn’t change app testing', { description: error instanceof Error ? error.message : String(error) });
        } finally {
            setSaving(null);
        }
    };
    const fixed = agent.docker ? `Always on: Docker runs in ${name}’s sandbox all the time.` : null;
    return (
        <section className="mt-6" data-testid="agent-app-testing">
            <h3 className="text-xs font-medium text-muted-foreground">App testing</h3>
            <p className="mt-1.5 text-[13px] leading-snug text-muted-foreground">
                Lets {name} start your app and a test database to check its work.
                {hourly !== null && ` About $${hourly.toFixed(2)}/hour while it’s on, nothing while idle.`}
                {agent.machineId && ' On its machine it costs nothing more, and the machine’s own choice applies too: the stricter one holds.'}
            </p>
            {fixed ? (
                <p className="mt-2 text-[13px] leading-snug">{fixed}</p>
            ) : (
                <>
                    <div role="radiogroup" aria-label="App testing" className="mt-2.5 inline-flex rounded-full bg-foreground/[0.06] p-0.5">
                        {MODES.map(([value, label]) => (
                            <button
                                key={value}
                                type="button"
                                role="radio"
                                aria-checked={mode === value}
                                disabled={saving !== null}
                                onClick={() => void pick(value)}
                                className={cn(
                                    'h-7 whitespace-nowrap rounded-full px-3 text-[12.5px] transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-wait',
                                    mode === value ? 'bg-popover font-medium text-foreground shadow-sm ring-1 ring-inset ring-border dark:ring-foreground/[0.12]' : 'text-muted-foreground hover:text-foreground'
                                )}
                            >
                                {label}
                            </button>
                        ))}
                    </div>
                    <p className="mt-1.5 text-xs leading-snug text-muted-foreground">{modeSaid(mode, name)}</p>
                </>
            )}
        </section>
    );
}
