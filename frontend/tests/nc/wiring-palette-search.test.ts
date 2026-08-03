// Live check that the agent wiring palette ("Add trigger" / "Add tool") finds
// services by the words users actually type, against the REAL node registry —
// the vitest unit test can only cover hand-picked node definitions. The
// regression this guards: rows were built from the type-derived label, so the
// Schedule trigger was only reachable by typing "trigger cron".
import { buildWiringServices } from '~/components/workflow/AgentWiringPalette';
import { filterNodeServices } from '~/utils/nodeServiceSearch';

export default async function () {
    const triggers = buildWiringServices('trigger');
    const tools = buildWiringServices('tool');
    if (triggers.length < 10 || tools.length < 10)
        throw new Error(
            `catalog looks empty: ${triggers.length} triggers, ${tools.length} tools`
        );

    const top = (role: 'trigger' | 'tool', q: string, n = 5) =>
        filterNodeServices(role === 'trigger' ? triggers : tools, q, role)
            .slice(0, n)
            .map((s) => s.nodeType);

    const cron = triggers.find((t) => t.nodeType === 'trigger-cron');
    if (cron?.label !== 'Schedule')
        throw new Error(
            `schedule trigger should be labelled "Schedule", got "${cron?.label}"`
        );

    const expectFirst = (
        role: 'trigger' | 'tool',
        q: string,
        nodeType: string
    ) => {
        const rows = top(role, q);
        if (rows[0] !== nodeType)
            throw new Error(
                `"${q}" should rank ${nodeType} first, got [${rows.join(', ')}]`
            );
        return rows;
    };

    const results: Record<string, unknown> = {
        triggerCount: triggers.length,
        toolCount: tools.length,
        schedule: expectFirst('trigger', 'schedule', 'trigger-cron'),
        cron: expectFirst('trigger', 'cron', 'trigger-cron'),
        everyDay: expectFirst('trigger', 'every day', 'trigger-cron'),
        webhook: expectFirst('trigger', 'http endpoint', 'trigger-webhook'),
        email: expectFirst('trigger', 'incoming mail', 'trigger-email'),
        // Action-band recall: neither word is in the node's own identity.
        createIssue: top('tool', 'create issue'),
        sendMessage: top('tool', 'send message'),
        reminder: expectFirst('tool', 'reminder', 'alarm'),
    };

    for (const key of ['createIssue', 'sendMessage'] as const) {
        if ((results[key] as string[]).length === 0)
            throw new Error(`"${key}" query matched no service`);
    }
    if (!(results.createIssue as string[]).includes('automation-linear'))
        throw new Error(
            `"create issue" should surface Linear, got ${JSON.stringify(results.createIssue)}`
        );
    if (!(results.sendMessage as string[]).includes('automation-slack'))
        throw new Error(
            `"send message" should surface Slack, got ${JSON.stringify(results.sendMessage)}`
        );

    // A service named by the user must outrank one matched only by its actions.
    const slackFirst = top('tool', 'slack')[0];
    if (slackFirst !== 'automation-slack')
        throw new Error(`"slack" should rank Slack first, got ${slackFirst}`);

    return results;
}
