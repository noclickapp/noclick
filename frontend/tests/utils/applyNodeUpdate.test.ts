// Round-trip property tests for the node data model in ~/lib/applyNodeUpdate.
//
// These tests guard the invariant that defines this module's existence: a node
// loaded with createWorkflowNode, serialized back out with buildSaveConfig,
// and re-loaded is structurally identical. If a new field is ever added to
// NodeUpdatePayload but missed in createWorkflowNode's read path or
// buildSaveConfig's write path, ONE of these tests fails immediately — that's
// the structural prevention for the kind of drift that hid the `_settings`
// reload bug on the node-settings regression fix.

import { describe, it, expect } from 'vitest';
import {
    applyNodeUpdate,
    applyNodeStatuses,
    createWorkflowNode,
    buildSaveConfig,
    serializeNodeForSave,
    normalizeNodeUpdatePayload,
    rawConfigToPayload,
    getNodeFieldValue,
} from '~/lib/applyNodeUpdate';
import type { Node } from '@xyflow/react';

const baseRaw = () => ({
    // config fields (flat alongside metadata in the wire format)
    message: 'hello',
    chatId: '12345',
    nested: { a: 1, b: [2, 3] },
    // user-toggled settings — the field whose drift motivated this test
    _settings: {
        onError: 'continueErrorOutput' as const,
        retryOnFail: 'true',
        maxTries: '3',
    },
    // top-level metadata
    operation: 'send_message',
    label: 'Send to Slack',
    goal: 'Notify the team',
    credentialIds: { slack_token: 'cred-1' },
    userFields: ['message'],
    operationReason: 'because',
    disabled: false,
    mockedOutput: { foo: 'bar' },
    credentials: { extra: 'inline' },
    content: 'sticky body',
    color: 3,
});

describe('applyNodeUpdate data model', () => {
    describe('round-trip invariant', () => {
        it('createWorkflowNode → buildSaveConfig → createWorkflowNode is a fixed point', () => {
            const raw = baseRaw();
            const first = createWorkflowNode(
                'n1',
                'automation-slack',
                { x: 10, y: 20 },
                raw
            );
            const saved = buildSaveConfig(first);
            const second = createWorkflowNode(
                'n1',
                'automation-slack',
                { x: 10, y: 20 },
                saved
            );
            expect(second.data).toEqual(first.data);
        });

        it('_settings round-trips through data.config._settings (the reload bug from the node-settings regression fix)', () => {
            const raw = {
                ...baseRaw(),
                _settings: { onError: 'continueErrorOutput' },
            };
            const node = createWorkflowNode(
                'n1',
                'automation-slack',
                { x: 0, y: 0 },
                raw
            );
            // Lives at data.config._settings — the only location.
            expect((node.data as any).config._settings).toEqual({
                onError: 'continueErrorOutput',
            });
            // NOT at top-level data._settings.
            expect((node.data as any)._settings).toBeUndefined();
            // Round-trips through save.
            const saved = buildSaveConfig(node);
            expect(saved._settings).toEqual({ onError: 'continueErrorOutput' });
            const reloaded = createWorkflowNode(
                'n1',
                'automation-slack',
                { x: 0, y: 0 },
                saved
            );
            expect((reloaded.data as any).config._settings).toEqual({
                onError: 'continueErrorOutput',
            });
        });

        it('preserves every persisted top-level field through a save round-trip', () => {
            const raw = baseRaw();
            const node = createWorkflowNode(
                'n1',
                'automation-slack',
                { x: 0, y: 0 },
                raw
            );
            const saved = buildSaveConfig(node);
            // Each persisted top-level field appears in the save blob.
            for (const field of [
                'operation',
                'operationReason',
                'userFields',
                'goal',
                'label',
                'credentialIds',
                'disabled',
                'mockedOutput',
                'credentials',
                'content',
                'color',
            ]) {
                expect(saved[field]).toEqual(
                    (raw as Record<string, any>)[field]
                );
            }
        });

        it('persist:false runtime fields never appear in the save blob', () => {
            const raw = {
                ...baseRaw(),
                // restore:true (server-authored, displayed on the canvas)
                output: { server: 'wrote-this' },
                outputTimestamp: 123,
                _outputStoredLocally: true,
                _outputSizeBytes: 4096,
                // restore:false (client-only transient)
                configValid: true,
                error: 'old error',
                executionState: 'completed',
                workflowAnimating: true,
                _executionId: 'exec-1',
            };
            const node = createWorkflowNode(
                'n1',
                'automation-slack',
                { x: 0, y: 0 },
                raw
            );
            const saved = buildSaveConfig(node);
            // Nothing persist:false makes it into the save blob.
            for (const k of [
                'output',
                'outputTimestamp',
                '_outputStoredLocally',
                '_outputSizeBytes',
                'configValid',
                'error',
                'executionState',
                'workflowAnimating',
                '_executionId',
            ]) {
                expect(
                    saved[k],
                    `${k} should not be in save blob`
                ).toBeUndefined();
            }
        });

        it('output-display fields are restore:false (not lifted from a saved blob) but apply via extras', () => {
            // Post-CAS-cutover contract: node outputs live SOLELY in the CAS. A
            // saved config blob's output/* must NOT be lifted on hydrate — a stale
            // pre-cutover blob can't shadow the fresh CAS value. They reach data.*
            // only via the CAS-backed get_node_outputs response (applied as
            // `extras`) + the live workflow:node:output event, and never save back.
            const raw = {
                ...baseRaw(),
                output: { stale: 'from-blob' },
                outputTimestamp: 9999,
                _outputStoredLocally: true,
                _outputSizeBytes: 4096,
            };
            const node = createWorkflowNode(
                'n1',
                'automation-slack',
                { x: 0, y: 0 },
                raw
            );
            const data = node.data as Record<string, any>;
            // restore:false → dropped on hydrate (not on data, not in config).
            expect(data.output).toBeUndefined();
            expect(data.outputTimestamp).toBeUndefined();
            expect(data._outputStoredLocally).toBeUndefined();
            expect(data._outputSizeBytes).toBeUndefined();
            expect(data.config.output).toBeUndefined();

            // The CAS hydration path applies output via extras → lands on data.output.
            const hydrated = applyNodeUpdate(node, {
                extras: { output: { server: 'cas' }, outputTimestamp: 1 },
            });
            const hdata = hydrated.data as Record<string, any>;
            expect(hdata.output).toEqual({ server: 'cas' });
            expect(hdata.outputTimestamp).toBe(1);

            // Save blob never carries them (persist:false) — even after the extras apply.
            const saved = buildSaveConfig(hydrated);
            expect(saved.output).toBeUndefined();
            expect(saved.outputTimestamp).toBeUndefined();
            expect(saved._outputStoredLocally).toBeUndefined();
            expect(saved._outputSizeBytes).toBeUndefined();
        });

        it('restore:false fields never appear on data after hydrate', () => {
            // configValid / workflowAnimating / error / executionState etc.
            // are pure client state. Even if a (stale or malicious) blob
            // arrives with them set, hydrate must drop them.
            const raw = {
                ...baseRaw(),
                configValid: true,
                error: 'stale',
                executionState: 'running',
                workflowAnimating: true,
                _executionId: 'exec-1',
                _timeToFillMs: 250,
                _hasPresetPosition: true,
                progress: 'stale streaming text',
            };
            const node = createWorkflowNode(
                'n1',
                'automation-slack',
                { x: 0, y: 0 },
                raw
            );
            const data = node.data as Record<string, any>;
            for (const k of [
                'configValid',
                'error',
                'executionState',
                'workflowAnimating',
                '_executionId',
                '_timeToFillMs',
                '_hasPresetPosition',
                'progress',
            ]) {
                expect(
                    data[k],
                    `${k} should not survive hydrate`
                ).toBeUndefined();
                expect(
                    data.config[k],
                    `${k} should not leak into data.config`
                ).toBeUndefined();
            }
        });

        it('survives an applyNodeUpdate edit in the middle of the round trip', () => {
            // load → edit → save → load — the path that broke for _settings.
            const raw = baseRaw();
            const loaded = createWorkflowNode(
                'n1',
                'automation-slack',
                { x: 0, y: 0 },
                raw
            );
            const edited = applyNodeUpdate(loaded, {
                config: {
                    _settings: { onError: 'stopWorkflow' },
                    message: 'updated text',
                },
            });
            const saved = buildSaveConfig(edited);
            expect(saved._settings).toEqual({ onError: 'stopWorkflow' });
            expect(saved.message).toBe('updated text');
            const reloaded = createWorkflowNode(
                'n1',
                'automation-slack',
                { x: 0, y: 0 },
                saved
            );
            expect((reloaded.data as any).config._settings).toEqual({
                onError: 'stopWorkflow',
            });
            expect((reloaded.data as any).config.message).toBe('updated text');
        });
    });

    describe('applyNodeUpdate behavior', () => {
        it('places _settings inside data.config when edited via the config field path', () => {
            const blank = createWorkflowNode('n1', 'automation-slack', {
                x: 0,
                y: 0,
            });
            const updated = applyNodeUpdate(blank, {
                config: { _settings: { onError: 'continueErrorOutput' } },
            });
            expect((updated.data as any).config._settings).toEqual({
                onError: 'continueErrorOutput',
            });
            expect((updated.data as any)._settings).toBeUndefined();
        });

        it('null in config deletes the key (existing semantics preserved)', () => {
            const start = createWorkflowNode(
                'n1',
                'automation-slack',
                { x: 0, y: 0 },
                {
                    message: 'hi',
                    _settings: { onError: 'continueErrorOutput' },
                }
            );
            const cleared = applyNodeUpdate(start, {
                config: { message: null },
            });
            expect((cleared.data as any).config.message).toBeUndefined();
            // unrelated keys untouched
            expect((cleared.data as any).config._settings).toEqual({
                onError: 'continueErrorOutput',
            });
        });

        it('mockedOutput === null deletes it from top-level data', () => {
            const start = createWorkflowNode(
                'n1',
                'automation-slack',
                { x: 0, y: 0 },
                {
                    mockedOutput: { foo: 'bar' },
                }
            );
            expect((start.data as any).mockedOutput).toEqual({ foo: 'bar' });
            const cleared = applyNodeUpdate(start, { mockedOutput: null });
            expect((cleared.data as any).mockedOutput).toBeUndefined();
        });

        it('extras spread onto top-level data unchanged', () => {
            const blank = createWorkflowNode('n1', 'automation-slack', {
                x: 0,
                y: 0,
            });
            const updated = applyNodeUpdate(blank, {
                extras: { mcpAnimationState: 'running' },
            });
            expect((updated.data as any).mcpAnimationState).toBe('running');
        });
    });

    describe('normalizeNodeUpdatePayload', () => {
        it('routes known top-level fields to the payload and unknown ones to extras', () => {
            const raw = {
                label: 'Foo',
                disabled: true,
                someUnknownKey: 'goes-to-extras',
                config: { message: 'hi' },
            };
            const payload = normalizeNodeUpdatePayload(raw);
            expect(payload.label).toBe('Foo');
            expect(payload.disabled).toBe(true);
            expect(payload.config).toEqual({ message: 'hi' });
            expect(payload.extras).toEqual({
                someUnknownKey: 'goes-to-extras',
            });
        });
    });

    describe('rawConfigToPayload', () => {
        // The MCP builder sends node_updated events carrying the flat config
        // blob (config fields + metadata mixed at the top level). This is the
        // converter useMCPBuilderEvents relies on to route credentialIds to
        // data.credentialIds — without it, an auto-selected credential lands
        // at data.config.credentialIds where NodeCredentials can't see it.
        it('routes credentialIds and metadata to top-level, config fields to config', () => {
            const blob = {
                message: 'hello',
                channel: '#general',
                operation: 'send_message',
                label: 'Send to Slack',
                credentialIds: { slack_oauth: 'cred-1' },
            };
            const payload = rawConfigToPayload(blob);
            expect(payload.credentialIds).toEqual({ slack_oauth: 'cred-1' });
            expect(payload.label).toBe('Send to Slack');
            expect(payload.operation).toBe('send_message');
            expect(payload.config).toEqual({
                message: 'hello',
                channel: '#general',
            });
        });

        it('applied to a node, an auto-selected credential lands at data.credentialIds', () => {
            const node = createWorkflowNode(
                'n1',
                'automation-slack',
                { x: 0, y: 0 },
                {}
            );
            const updated = applyNodeUpdate(
                node,
                rawConfigToPayload({ credentialIds: { slack_oauth: 'cred-1' } })
            );
            expect((updated.data as Record<string, any>).credentialIds).toEqual(
                { slack_oauth: 'cred-1' }
            );
            expect(
                (updated.data as Record<string, any>).config.credentialIds
            ).toBeUndefined();
        });
    });

    describe('serializeNodeForSave', () => {
        it('emits id, type, position, and config blob', () => {
            const node = createWorkflowNode(
                'n1',
                'automation-slack',
                { x: 10, y: 20 },
                baseRaw()
            );
            const serialized = serializeNodeForSave(node);
            expect(serialized.id).toBe('n1');
            expect(serialized.type).toBe('automation-slack');
            expect(serialized.position).toEqual({ x: 10, y: 20 });
            expect(serialized.config).toEqual(buildSaveConfig(node));
        });
    });

    describe('createWorkflowNode rejects bad ids', () => {
        it('throws when id is missing', () => {
            expect(() =>
                createWorkflowNode('', 'automation-slack', { x: 0, y: 0 })
            ).toThrow(/id is required/);
            expect(() =>
                // @ts-expect-error testing runtime guard against bad input
                createWorkflowNode(undefined, 'automation-slack', {
                    x: 0,
                    y: 0,
                })
            ).toThrow(/id is required/);
        });
    });

    // ------------------------------------------------------------------
    // Source-tree guard: no code outside this module is allowed to mutate
    // node.data by manually spreading it. Every mutation must route through
    // applyNodeUpdate / updateNodeInList / createWorkflowNode so the field
    // placement registry stays the single source of truth.
    //
    // Catches the regression pattern that produced this whole normalization
    // project: `data: { ...node.data, X: ... }` writers that bypass the
    // registry and put fields in the wrong slot (or invent slots).
    // ------------------------------------------------------------------
    describe('source-tree guard: no manual data spreads', () => {
        it('no ReactFlow-aware file under app/ contains `data: { ...X.data` outside the registry', async () => {
            const { promises: fs } = await import('node:fs');
            const path = await import('node:path');
            // Pattern: `data:` + whitespace + `{` + whitespace + spread + captured identifier + `.data`.
            // \s* matches across newlines so multi-line spreads are caught too:
            //   data: {
            //     ...node.data,
            //     X: ...
            //   }
            // Run against full file content (not per-line) — derive line
            // number from the match offset for the error report.
            const PATTERN = /data\s*:\s*\{\s*\.\.\.([a-zA-Z_$][\w$]*)\.data\b/g;
            // Edges have their own data bag (ReactFlow Edge<T>); not governed
            // by the node registry. Common edge-variable names skipped.
            const isEdgeLike = (id: string) =>
                id === 'edge' || /Edge$/.test(id) || id === 'e';
            // Only files that actually touch ReactFlow nodes can violate this
            // contract. Anything else (UsageDashboard caches, REST response
            // objects, etc.) that happens to spread an `X.data` field is on
            // its own data model and shouldn't be flagged here.
            const REACTFLOW_IMPORT = '@xyflow/react';
            // The single legitimate site is applyNodeUpdate.ts itself, which
            // BUILDS the new data object — it doesn't bypass the contract.
            const ALLOW_FILES = new Set<string>([
                path.resolve(__dirname, '../../app/lib/applyNodeUpdate.ts'),
            ]);

            const appRoot = path.resolve(__dirname, '../../app');
            const offenders: string[] = [];

            async function walk(dir: string): Promise<void> {
                const entries = await fs.readdir(dir, { withFileTypes: true });
                await Promise.all(
                    entries.map(async (entry) => {
                        const full = path.join(dir, entry.name);
                        if (entry.isDirectory()) {
                            if (
                                entry.name === 'node_modules' ||
                                entry.name === 'build' ||
                                entry.name.startsWith('.')
                            ) {
                                return;
                            }
                            // The /animations playground is a throwaway visual demo with its
                            // own minimal node shape ({executionState, completedAt}); it
                            // deliberately doesn't use the production node data model, so the
                            // applyNodeUpdate contract doesn't apply to it.
                            if (
                                full ===
                                path.resolve(appRoot, 'components/animations')
                            )
                                return;
                            return walk(full);
                        }
                        if (!entry.isFile()) return;
                        if (!(full.endsWith('.ts') || full.endsWith('.tsx')))
                            return;
                        if (ALLOW_FILES.has(full)) return;
                        const content = await fs.readFile(full, 'utf8');
                        if (!content.includes(REACTFLOW_IMPORT)) return;

                        PATTERN.lastIndex = 0;
                        let match: RegExpExecArray | null;
                        while ((match = PATTERN.exec(content)) !== null) {
                            if (isEdgeLike(match[1])) continue;
                            // Convert offset → line number for a readable report.
                            const line = content
                                .slice(0, match.index)
                                .split('\n').length;
                            const snippet = content
                                .slice(match.index, match.index + 80)
                                .replace(/\s+/g, ' ');
                            offenders.push(`${full}:${line}: ${snippet}…`);
                        }
                    })
                );
            }

            await walk(appRoot);

            if (offenders.length > 0) {
                throw new Error(
                    `Found ${offenders.length} site(s) that bypass applyNodeUpdate by manually spreading node.data:\n` +
                        offenders.map((o) => `  - ${o}`).join('\n') +
                        `\n\nRoute these through applyNodeUpdate / updateNodeInList / createWorkflowNode so ` +
                        `the TOP_LEVEL_FIELDS registry stays the single source of truth for field placement.`
                );
            }
        });
    });

    describe('getNodeFieldValue', () => {
        // Regression for the Guided Setup pill bug: schema-derived field names
        // were read as data[name], silently missing config values at
        // data.config[name]. getNodeFieldValue routes the read through the
        // canonical TOP_LEVEL_FIELDS list so the location can't drift.
        const slack = createWorkflowNode(
            's1',
            'automation-slack',
            { x: 0, y: 0 },
            baseRaw()
        );

        it('reads top-level fields from data.<name>', () => {
            expect(getNodeFieldValue(slack, 'operation')).toBe('send_message');
            expect(getNodeFieldValue(slack, 'label')).toBe('Send to Slack');
            expect(getNodeFieldValue(slack, 'credentialIds')).toEqual({
                slack_token: 'cred-1',
            });
        });

        it('reads unknown names from data.config.<name>', () => {
            expect(getNodeFieldValue(slack, 'message')).toBe('hello');
            expect(getNodeFieldValue(slack, 'chatId')).toBe('12345');
            // Discriminator fields that happen to be config-shaped (e.g. agent's
            // model_type) are read from data.config, not the top level.
            const agent = createWorkflowNode(
                'a1',
                'agent',
                { x: 0, y: 0 },
                {
                    model_type: 'claude_code',
                    message: 'hi',
                }
            );
            expect(getNodeFieldValue(agent, 'model_type')).toBe('claude_code');
        });

        it('returns undefined for missing fields without throwing on missing data/config', () => {
            const empty: {
                id: string;
                type: string;
                position: { x: number; y: number };
                data: Record<string, unknown>;
            } = {
                id: 'e1',
                type: 'agent',
                position: { x: 0, y: 0 },
                data: {},
            };
            expect(
                getNodeFieldValue(
                    empty as Parameters<typeof getNodeFieldValue>[0],
                    'message'
                )
            ).toBeUndefined();
            expect(
                getNodeFieldValue(
                    empty as Parameters<typeof getNodeFieldValue>[0],
                    'operation'
                )
            ).toBeUndefined();
        });
    });

    // Last-run status restoration. This is the logic shared by every workflow load
    // path (initial workflow:get AND the collaborative-reconnect refetch). The bug it
    // guards: a reconnect refetched the graph (mergeServerNodes, which drops
    // _lastRunStatus) WITHOUT re-applying node_statuses, silently wiping the
    // "✓/✗ N ago" chips when you closed the tab and came back.
    describe('applyNodeStatuses', () => {
        const mk = (id: string, data: Record<string, unknown> = {}): Node => ({
            id,
            type: 'automation-gmail',
            position: { x: 0, y: 0 },
            data,
        });

        it('applies status to a freshly-loaded node (no _lastRunStatus yet)', () => {
            const out = applyNodeStatuses([mk('a')], {
                a: { status: 'completed', finishedAt: 123, error: null },
            });
            expect(out[0].data._lastRunStatus).toBe('completed');
            expect(out[0].data._lastRunAt).toBe(123);
            expect(out[0].data._lastRunError).toBeUndefined();
        });

        it('restores status after a reconnect-style reload that dropped it (regression)', () => {
            // mergeServerNodes returns the loaded node WITHOUT _lastRunStatus; the map
            // must put it back so the chip/aurora survives the reconnect.
            const reloaded = mk('a'); // no _lastRunStatus (loaded from save blob)
            const out = applyNodeStatuses([reloaded], {
                a: { status: 'error', finishedAt: 9, error: 'boom' },
            });
            expect(out[0].data._lastRunStatus).toBe('error');
            expect(out[0].data._lastRunError).toBe('boom');
        });

        it('does NOT clobber a node that already owns a status this session', () => {
            const node = mk('a', { _lastRunStatus: 'error', _lastRunAt: 5 });
            const out = applyNodeStatuses([node], {
                a: { status: 'completed', finishedAt: 99 },
            });
            expect(out[0].data._lastRunStatus).toBe('error'); // live state wins
        });

        it('does NOT clobber a node that is currently running', () => {
            const node = mk('a', { executionState: 'running' });
            const out = applyNodeStatuses([node], {
                a: { status: 'completed', finishedAt: 99 },
            });
            expect(out[0].data._lastRunStatus).toBeUndefined();
            expect(out[0].data.executionState).toBe('running');
        });

        it('leaves nodes absent from the status map untouched', () => {
            const out = applyNodeStatuses([mk('a'), mk('b')], {
                a: { status: 'completed', finishedAt: 1 },
            });
            expect(out[0].data._lastRunStatus).toBe('completed');
            expect(out[1].data._lastRunStatus).toBeUndefined();
        });

        it('returns the list unchanged for an empty/undefined map', () => {
            const list = [mk('a')];
            expect(applyNodeStatuses(list, {})).toBe(list);
            expect(applyNodeStatuses(list, undefined)).toBe(list);
        });
    });
});
