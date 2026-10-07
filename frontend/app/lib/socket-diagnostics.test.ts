import { describe, expect, it } from 'vitest';
import {
    diagnosticAuthErrorCode, diagnosticDisconnectReason, diagnosticSocketText, projectSocketDiagnostics,
    REDACTED_SOCKET_DATA,
} from './socket-diagnostics';

const SECRET = 'synthetic-diagnostic-secret';

describe('socket diagnostic projection', () => {
    it.each([
        'drip:oauth:exchange', 'mcp:oauth:exchange', 'credential:get',
        'credential:create', 'credential:update', 'github-copilot:auth:poll',
        'update_auth', 'otp:verify', 'password:reset', 'provider:callback',
        'workflow:collab_token', 'instance_oauth:list', 'instance_keys:set',
        'instance_smtp:set', 'trigger_tests:set_credential', 'workflow:mcp:list_credentials',
        'share:invite_link', 'share:invite_accept', 'agent_share:get_or_create', 'shared_agent:send',
        'future:event', 'response', 'error', undefined,
    ])('omits all content for sensitive or unclassified context %s', event => {
        const payload = { opaque: SECRET, nested: [{ unfamiliar: SECRET }], error: new Error(SECRET) };
        expect(projectSocketDiagnostics(event, payload)).toBe(REDACTED_SOCKET_DATA);
        expect(projectSocketDiagnostics(event, SECRET)).toBe(REDACTED_SOCKET_DATA);
        expect(payload.opaque).toBe(SECRET);
    });

    it('keeps known workflow structure and token counts while redacting nested secret keys', () => {
        const data = { workflow_id: 'fixture-workflow', status: 'complete', count: 2,
            nested: [{ clientSecret: SECRET, credential_data: { opaque: SECRET }, title: 'Fixture' }],
            headers: { Authorization: `Bearer ${SECRET}`, 'Set-Cookie': SECRET },
            error: 'Workflow unavailable', total_tokens: 20 };
        const projected = projectSocketDiagnostics('workflow:get', data);
        expect(projected).toEqual({ ...data,
            nested: [{ clientSecret: REDACTED_SOCKET_DATA, credential_data: REDACTED_SOCKET_DATA, title: 'Fixture' }],
            headers: { Authorization: REDACTED_SOCKET_DATA, 'Set-Cookie': REDACTED_SOCKET_DATA } });
        expect(JSON.stringify(projected)).not.toContain(SECRET);
        expect(projectSocketDiagnostics('active_gen:token_progress', { tokens_used: 25 })).toEqual({ tokens_used: 25 });
        expect(data.nested[0].clientSecret).toBe(SECRET);
    });

    it('retains bounded ordinary errors without stack/cause or auth-bearing URLs', () => {
        const error = new Error(`Workflow unavailable; Bearer ${SECRET} https://fixture.invalid/callback?code=${SECRET}`);
        Object.assign(error, { cause: { secret: SECRET } });
        const projected = projectSocketDiagnostics('workflow:get', error);
        expect(projected).toEqual({ name: 'Error', message: 'Workflow unavailable; [Authorization omitted] [Private URL omitted]' });
        expect(JSON.stringify(projected)).not.toContain(SECRET);
        expect(projectSocketDiagnostics(undefined, error)).toBe(REDACTED_SOCKET_DATA);
        expect(diagnosticSocketText('workflow:get', new Error('Workflow unavailable'))).toBe('Workflow unavailable');
    });

    it('redacts actual HTTP key/value header rows while preserving harmless headers', () => {
        const payload = { config: { headers: [
            { key: 'Authorization', value: SECRET, enabled: true },
            { key: 'X-API-Key', value: SECRET, enabled: true },
            { key: 'X-Auth-Token', value: SECRET, enabled: true },
            { key: 'Content-Type', value: 'application/json', enabled: true },
        ] } };
        expect(projectSocketDiagnostics('workflow:update', payload)).toEqual({ config: { headers: [
            { key: 'Authorization', value: REDACTED_SOCKET_DATA, enabled: true },
            { key: 'X-API-Key', value: REDACTED_SOCKET_DATA, enabled: true },
            { key: 'X-Auth-Token', value: REDACTED_SOCKET_DATA, enabled: true },
            { key: 'Content-Type', value: 'application/json', enabled: true },
        ] } });
        expect(payload.config.headers[0].value).toBe(SECRET);
        expect(projectSocketDiagnostics('share:invite_link', { token: SECRET, url: `https://fixture.invalid/i/${SECRET}` })).toBe(REDACTED_SOCKET_DATA);
    });

    it('does not invoke getters/toJSON or retain unsupported instances and binary references', () => {
        const data = Object.defineProperty({ toJSON: () => { throw new Error(SECRET); } }, 'value', {
            enumerable: true, get() { throw new Error(SECRET); },
        });
        expect(() => JSON.stringify(projectSocketDiagnostics('workflow:get', data))).not.toThrow();
        expect(projectSocketDiagnostics('workflow:get', new Uint8Array([1, 2]))).toBe('[Binary data omitted]');
        expect(projectSocketDiagnostics('workflow:get', new Date())).toBe('[Diagnostic value omitted]');
        const proxy = new Proxy({}, { getPrototypeOf() { throw new Error(SECRET); } });
        expect(projectSocketDiagnostics('workflow:get', proxy)).toBe('[Diagnostic value omitted]');
        expect(projectSocketDiagnostics({} as string, data)).toBe(REDACTED_SOCKET_DATA);
    });

    it('bounds cyclic, deep, wide and long diagnostic input', () => {
        const cycle: Record<string, unknown> = {}; cycle.self = cycle;
        expect(JSON.stringify(projectSocketDiagnostics('workflow:get', cycle))).toContain('Circular');
        let deep: unknown = SECRET;
        for (let index = 0; index < 10000; index++) deep = { child: deep };
        expect(JSON.stringify(projectSocketDiagnostics('workflow:get', deep))).not.toContain(SECRET);
        const wide = Object.fromEntries(Array.from({ length: 500 }, (_, index) => [`field${index}`, index]));
        expect(Object.keys(projectSocketDiagnostics('workflow:get', wide) as object)).toHaveLength(50);
        expect((projectSocketDiagnostics('workflow:get', 'x'.repeat(10000)) as string).length).toBe(1000);
        expect((projectSocketDiagnostics('workflow:get', Array(10000).fill('fixture')) as unknown[]).length).toBe(50);
    });

    it('preserves only recognized auth machine codes and disconnect reasons', () => {
        for (const code of ['token_expired', 'token_invalid', 'missing_auth', 'auth_failed']) {
            expect(diagnosticAuthErrorCode(code)).toBe(code);
        }
        expect(diagnosticAuthErrorCode(SECRET)).toBeUndefined();
        expect(diagnosticDisconnectReason('ping timeout')).toBe('ping timeout');
        expect(diagnosticDisconnectReason(SECRET)).toBe('[Diagnostic value omitted]');
    });
});
