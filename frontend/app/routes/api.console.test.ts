import { afterEach, describe, expect, it, vi } from 'vitest';
import type { ActionFunctionArgs } from 'react-router';
import { action } from './api.console';

describe('api.console action', () => {
    const originalNodeEnv = process.env.NODE_ENV;

    afterEach(() => {
        process.env.NODE_ENV = originalNodeEnv;
        vi.restoreAllMocks();
    });

    it('keeps parser details and stack traces out of error responses', async () => {
        process.env.NODE_ENV = 'development';
        vi.spyOn(console, 'error').mockImplementation(() => undefined);
        const request = new Request('http://localhost/api/console', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: '{ invalid json',
        });

        const response = await action({ request } as ActionFunctionArgs);

        expect(response.status).toBe(500);
        expect(await response.json()).toEqual({
            success: false,
            error: 'Failed to write console log',
        });
    });
});
