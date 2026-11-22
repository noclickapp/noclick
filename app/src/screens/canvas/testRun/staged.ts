// What a workflow can stage a test run on, as the Test Run screen lists it: each trigger type the workflow has (one
// that reaches an agent), with the situations offered for it. A source lists them by the trigger's step type; this
// gives each the name, mark and wording the screen draws it with.
import type { MockRun, Provider, TriggerFixture } from './scenarios';

/** One trigger type's staged situations, as a source lists them. */
export interface StagedTrigger {
    node_type: string;
    /** The trigger step's selected operation: the frames respond to it (a pull request draws as one). */
    operation?: string | null;
    situations?: { key: string; name: string; lead: MockRun['lead'] }[];
}

/** Display identity per trigger step type that has a native rendering. */
const NODE_TYPE_META: Record<string, { provider: Provider | 'generic'; nodeName: string; label: string }> = {
    'automation-gmail': { provider: 'gmail', nodeName: 'Gmail', label: 'Staged email' },
    'automation-slack': { provider: 'slack', nodeName: 'Slack', label: 'Staged message · Slack' },
    'automation-whatsapp': { provider: 'whatsapp', nodeName: 'WhatsApp', label: 'Staged message · WhatsApp' },
    'automation-telegram': { provider: 'telegram', nodeName: 'Telegram', label: 'Staged message · Telegram' },
};

/** The staged list as the screen's triggers. A type with no native rendering keeps the generic semantics (the raw
 *  event, no editing) but wears its own name (`nameOf`) and its own logo (`iconSlug`): a trigger that can be tested
 *  today reads as one, not as unsupported. */
export function triggersOfStaged(staged: readonly StagedTrigger[], nameOf: (nodeType: string) => string): TriggerFixture[] {
    return staged.map((t) => {
        const meta = NODE_TYPE_META[t.node_type] ?? { provider: 'generic' as const, nodeName: nameOf(t.node_type), label: 'Staged event' };
        return {
            slug: t.node_type,
            name: meta.nodeName,
            nodeName: meta.nodeName,
            triggerLabel: meta.label,
            provider: meta.provider,
            operation: t.operation ?? undefined,
            iconSlug: t.node_type.replace(/^automation-/, '').replace(/-/g, '_'),
            mocks: (t.situations ?? []).map((s) => ({
                slug: s.key,
                backendKey: s.key,
                name: s.name,
                lead: s.lead,
                events: [],
                doneAt: 0,
                artifacts: null,
            })),
        };
    });
}
