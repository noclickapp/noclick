// Verifies the schema-driven generalization of the builder's inline
// "Create new …" affordances: they are derived from every node's create ops
// (x-creates-resource + x-resource-type) matched to its dynamic-option fields
// (x-resource-type), not from a hand-listed map.

import { describe, it, expect } from 'vitest';
import { getFieldAffordance, _getAllFieldAffordances } from '~/components/chat/drawer/builderInputAffordances';

const affordance = (nodeType: string, fieldKey: string) =>
    getFieldAffordance({ type: 'config', nodeType, fieldKey } as any);

describe('builderInputAffordances (schema-derived)', () => {
    it('preserves the originally hardcoded affordances', () => {
        // These were the 10 hand-listed entries; they must still resolve now
        // that the map is generated.
        for (const [node, field, op] of [
            ['automation-google-sheets', 'spreadsheet_id', 'create_new_spreadsheet'],
            ['automation-google-docs', 'document_id', 'create_new_document'],
            ['automation-google-slides', 'presentation_id', 'create_new_presentation'],
            ['automation-google-forms', 'form_id', 'create_new_form'],
            ['automation-google-tasks', 'task_list_id', 'create_new_task_list'],
            ['automation-google-drive', 'folder_id', 'create_folder'],
            ['automation-notion', 'database_id', 'create_page_database'],
            ['automation-slack', 'channel', 'create_channel'],
        ] as const) {
            const a = affordance(node, field);
            expect(a, `${node}::${field}`).not.toBeNull();
            expect(a!.label.toLowerCase()).toContain('create');
            expect(a!.message).toContain(op);
            expect(a!.message).toContain(node);
        }
    });

    it('generalizes to newly-annotated nodes (PostHog) with no per-node wiring', () => {
        for (const [field, op] of [
            ['dashboard_id', 'create_dashboard'],
            ['cohort_id', 'create_cohort'],
            ['insight_id', 'create_insight'],
            ['survey_id', 'create_survey'],
            ['destination_id', 'create_destination'],
            ['notebook_id', 'create_notebook'],
        ] as const) {
            const a = affordance('automation-posthog', field);
            expect(a, `posthog::${field}`).not.toBeNull();
            expect(a!.message).toContain(op);
        }
    });

    it('covers many nodes automatically (>= 150 affordances across many nodes)', () => {
        const all = _getAllFieldAffordances();
        const keys = Object.keys(all);
        expect(keys.length).toBeGreaterThanOrEqual(150);
        const nodes = new Set(keys.map((k) => k.split('::')[0]));
        expect(nodes.size).toBeGreaterThanOrEqual(55);
    });

    // The BuilderInputDrawer calls getFieldAffordance(current) where `current`
    // is the InputRequest the agentic builder emits for a config-field <ask>.
    // The backend (coder/workflow/agentic/commands.py) builds that request as
    // { type: 'config', nodeType: node.type, fieldKey: field } — so this test
    // exercises the EXACT runtime shape, proving each annotated node's create
    // affordance actually surfaces in the drawer (not just that the map exists).
    it('surfaces a create affordance for every annotated node via the real builder-ask shape', () => {
        const all = _getAllFieldAffordances();
        // one representative annotated node per batch shipped in this work
        const expectedNodes = [
            'automation-trello', 'automation-zendesk', 'automation-intercom', 'automation-confluence',
            'automation-github-rest', 'automation-bigquery', 'automation-elasticsearch', 'automation-pinecone',
            'automation-weaviate', 'automation-chroma', 'automation-mongodb',
            'automation-pipedrive', 'automation-quickbooks', 'automation-klaviyo', 'automation-attio', 'automation-expensify',
            'automation-sentry', 'automation-pagerduty', 'automation-launchdarkly', 'automation-databricks',
            'automation-tableau', 'automation-microsoft-teams',
            'automation-cloudflare', 'automation-outlook', 'automation-sigma', 'automation-typeform',
            'automation-basedash', 'automation-atlas-admin', 'automation-extend',
            // name-keyed resources: the identifier is the name the agent supplies
            // at create time, so the affordance must surface even though the
            // create response echoes no id (no x-resource-id-path).
            'automation-snowflake', 'automation-milvus', 'automation-qdrant', 'automation-firestore',
        ];
        for (const node of expectedNodes) {
            const fieldKey = Object.keys(all)
                .filter((k) => k.startsWith(`${node}::`))
                .map((k) => k.slice(node.length + 2))[0];
            expect(fieldKey, `no affordance generated for ${node}`).toBeTruthy();
            // drive it through the public API with the backend's request shape
            const a = getFieldAffordance({ type: 'config', nodeType: node, fieldKey } as any);
            expect(a, `${node}::${fieldKey} did not resolve`).not.toBeNull();
            expect(a!.label.toLowerCase()).toContain('create');
            expect(a!.message).toContain(node);
            expect(a!.message).toMatch(/create|Create/);
        }
    });

    it('offers nothing for a field with no matching create op', () => {
        // person_id has a picker but PostHog has no create-person op.
        expect(affordance('automation-posthog', 'person_id')).toBeNull();
        // a plain non-resource field
        expect(affordance('automation-posthog', 'limit')).toBeNull();
    });

    it('returns null for non-config / missing input', () => {
        expect(getFieldAffordance(undefined)).toBeNull();
        expect(getFieldAffordance({ type: 'credential', nodeType: 'x' } as any)).toBeNull();
        expect(getFieldAffordance({ type: 'config', nodeType: 'automation-posthog' } as any)).toBeNull();
    });
});
