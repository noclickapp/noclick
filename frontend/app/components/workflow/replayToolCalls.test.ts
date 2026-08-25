// Unit tests for toReplayToolCalls — the mapper that turns an agent response
// run's embedded `tool_calls` package into ReplayToolCall rows. Some runtimes
// attach calls only to this package, so the mapping is a first-class source for
// the popup.

import { describe, it, expect } from 'vitest';
import { toReplayToolCalls } from './ReplayToolCallsPanel';

describe('toReplayToolCalls', () => {
    it('returns [] when the output carries no package', () => {
        expect(toReplayToolCalls(undefined)).toEqual([]);
        expect(toReplayToolCalls(null)).toEqual([]);
        expect(toReplayToolCalls('a string')).toEqual([]);
        expect(toReplayToolCalls({ response: 'hi' })).toEqual([]); // no tool_calls key
        expect(toReplayToolCalls({ tool_calls: 'not an array' })).toEqual([]);
    });

    it('maps package fields and renames created_at → timestamp', () => {
        const out = {
            response: 'done',
            tool_calls: [{
                tool_name: 'linear__create_issue',
                tool_type: 'node_op',
                operation: 'create_issue',
                provider_node_id: 'p1',
                credential_id: 'cred-1',
                result_status: 'success',
                error: null,
                result_preview: 'ok',
                arguments: { title: 'Bug' },
                duration_ms: 12,
                model: 'codex',
                created_at: '2026-06-30T12:00:00+00:00',
            }],
        };
        const [call] = toReplayToolCalls(out);
        expect(call.tool_name).toBe('linear__create_issue');
        expect(call.tool_type).toBe('node_op');
        expect(call.operation).toBe('create_issue');
        expect(call.arguments).toEqual({ title: 'Bug' });
        expect(call.result_status).toBe('success');
        expect(call.duration_ms).toBe(12);
        expect(call.timestamp).toBe('2026-06-30T12:00:00+00:00'); // created_at → timestamp
    });

    it('coerces missing/odd fields to safe defaults', () => {
        const [call] = toReplayToolCalls({ tool_calls: [{}] });
        expect(call.tool_name).toBe('');
        expect(call.tool_type).toBe('');
        expect(call.result_status).toBe('success');
        expect(call.arguments).toBeNull();
        expect(call.duration_ms).toBeNull();
        expect(call.timestamp).toBeNull();
        expect(call.error).toBeNull();
    });

    it('preserves order and error rows', () => {
        const calls = toReplayToolCalls({
            tool_calls: [
                { tool_name: 'a', result_status: 'success' },
                { tool_name: 'b', result_status: 'error', error: 'boom' },
            ],
        });
        expect(calls.map(c => c.tool_name)).toEqual(['a', 'b']);
        expect(calls[1].error).toBe('boom');
    });
});
