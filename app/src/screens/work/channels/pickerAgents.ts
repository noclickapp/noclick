// Your agents as the channel pickers (Start a channel, a channel's Add an agent) list them: the NoClick of where the
// channel is first (a space's own, or in the personal space the account's own, named by `noclickNaming`), saying what it
// does in a channel, and every other platform agent with its model and harness named ("Sonnet 5.5 on Claude Code"),
// read from the harnesses' own model lists while a picker is open. No other NoClick is offered: the backend lets a
// space's channels hold only the space's.
import { useMemo } from 'react';
import { Agent } from 'noclick';
import type { AgentChoice } from '@/screens/channels/types';
import { harnessLabel } from '../agents/harness';
import { keptByNoClick, useNoClickId, useWorkV1, YOUR_NOCLICK } from '../agents/reads';
import { useSpaceNoClick } from '../intro';
import { listedModel, modelName } from '../newAgent/catalog';

export const NOCLICK_LISTENS = 'Listens here and tells you directly';

/** `reading`: the picker is open, so the models' names (and the space's NoClick) are worth reading. `workspaceId`: the
 *  space the channel is in, null for the personal space. */
export function usePickerAgents(agents: AgentChoice[], reading: boolean, workspaceId: string | null): AgentChoice[] {
    const noclick = useNoClickId();
    const ours = useSpaceNoClick(workspaceId, reading);
    const pairs = useMemo(
        () => [...new Set(agents.flatMap((a) => (a.harness && !keptByNoClick(a) ? [`${a.harness} ${a.model ?? ''}`] : [])))].sort(),
        [agents]
    );
    // The harnesses as the New agent picker reads them (the same key), then each model's name from its harness's list.
    const harnesses = useWorkV1(reading && pairs.length ? 'work:harnesses' : null, (client) => Agent.harnesses({ client }));
    const listed = harnesses.data;
    const names = useWorkV1(listed ? `work:model-names:${pairs.join(',')}` : null, async () => {
        const named = await Promise.all(
            pairs.map(async (pair) => {
                const [name, given] = pair.split(' ');
                const harness = listed!.find((h) => h.name === name);
                if (!harness) return [pair, null] as const;
                const model = given || harness.defaultModel;
                const found = listedModel(await harness.models({ search: model, limit: 10 }), model);
                const plain = modelName(found?.label, model);
                return [pair, harness.name === 'sdk' ? plain : `${plain} on ${harnessLabel(harness.name)}`] as const;
            })
        );
        return Object.fromEntries(named.filter((n): n is readonly [string, string] => n[1] !== null));
    });
    return useMemo(() => {
        const lead: AgentChoice[] = workspaceId
            ? ours
                ? [{ id: ours.agentId, name: ours.name, noclick: true, role: NOCLICK_LISTENS }]
                : []
            : agents.filter((a) => a.id === noclick).map((a) => ({ ...a, name: YOUR_NOCLICK, noclick: true, role: NOCLICK_LISTENS }));
        const rest = agents
            .filter((a) => !keptByNoClick(a))
            .map((a): AgentChoice => {
                const line = a.harness ? names.data?.[`${a.harness} ${a.model ?? ''}`] : undefined;
                return line ? { ...a, modelLine: line } : a;
            });
        return [...lead, ...rest];
    }, [agents, noclick, names.data, workspaceId, ours]);
}
