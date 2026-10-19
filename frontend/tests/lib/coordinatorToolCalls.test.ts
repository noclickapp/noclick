import { describe, expect, it } from 'vitest';
import { coordinatorToolCalls, failed } from '~/lib/coordinatorToolCalls';
import type { AgentChatStep } from '~/hooks/useAgentChat';

const step = (over: Partial<AgentChatStep>): AgentChatStep => ({ id: 's', title: '', status: 'completed', kind: 'tool', startedAt: 1000, ...over });

describe('coordinatorToolCalls', () => {
    it('reads a live call: the tool, its arguments and what it answered', () => {
        const [call] = coordinatorToolCalls([
            step({
                id: 'call_1',
                title: 'Calling connect_credential({"credential_type": "notion_oauth", "message": "Read your docs"})',
                detail: '{"status": "pending", "request_id": "r1", "url": "https://noclick.com/credential/provide/t1", "auto_resume": true}',
            }),
        ]);
        expect(call).toEqual({
            id: 'call_1',
            tool: 'connect_credential',
            args: { credential_type: 'notion_oauth', message: 'Read your docs' },
            result: { status: 'pending', request_id: 'r1', url: 'https://noclick.com/credential/provide/t1', auto_resume: true },
            running: false,
            startedAt: 1000,
        });
    });

    it('keeps what arrived whole of a title and a result the preview cut', () => {
        const [call] = coordinatorToolCalls([
            step({
                title: 'Calling request_build({"name": "Brief", "instructions": "Every morning read my inb',
                detail: '{"success": true, "job_id": "j1", "kind": "build", "workflow_id": "w1", "note": "The builder owns this build thr',
            }),
        ]);
        expect(call.args).toEqual({ name: 'Brief' });
        expect(call.result).toEqual({ success: true, job_id: 'j1', kind: 'build', workflow_id: 'w1' });
    });

    it('marks a call still running and leaves status rows and unnamed calls out', () => {
        const calls = coordinatorToolCalls([
            step({ kind: 'status', title: 'Thinking' }),
            step({ title: 'Tool call', detail: '{"ok": true}' }),
            step({ id: 'r', title: 'Calling job_status({})', status: 'in_progress' }),
        ]);
        expect(calls).toHaveLength(1);
        expect(calls[0]).toMatchObject({ tool: 'job_status', args: {}, running: true, result: undefined });
    });

    it('reads a restored row the same way', () => {
        // persistedEventsToChatMessages rebuilds rows as "Calling {tool}({arguments_preview})".
        const [call] = coordinatorToolCalls([step({ id: 'restored-0', title: 'Calling save_memory({"name": "brief-length"})', detail: '{"success": true, "memory": {"id": "m1", "version": 1}}' })]);
        expect(call.result).toEqual({ success: true, memory: { id: 'm1', version: 1 } });
    });
});

describe('failed', () => {
    it('is true for a refusal or an error and false for a result', () => {
        expect(failed({ success: false, error: 'no' })).toBe(true);
        expect(failed({ error: 'boom' })).toBe(true);
        expect(failed({ success: true })).toBe(false);
        expect(failed(undefined)).toBe(false);
    });
});
