import { afterEach, describe, expect, it } from 'vitest';

import { inboundEmailDomain } from '~/lib/inboundEmail';

const env = import.meta.env as Record<string, unknown>;
const originalLocal = env.VITE_NOCLICK_LOCAL;
const originalDomain = env.VITE_INBOUND_EMAIL_DOMAIN;

afterEach(() => {
    if (originalLocal === undefined) delete env.VITE_NOCLICK_LOCAL;
    else env.VITE_NOCLICK_LOCAL = originalLocal;
    if (originalDomain === undefined) delete env.VITE_INBOUND_EMAIL_DOMAIN;
    else env.VITE_INBOUND_EMAIL_DOMAIN = originalDomain;
});

describe('inboundEmailDomain', () => {
    it('keeps the hosted service owned default', () => {
        delete env.VITE_NOCLICK_LOCAL;
        delete env.VITE_INBOUND_EMAIL_DOMAIN;
        expect(inboundEmailDomain()).toBe('noclick.app');
    });

    it('disables inbound email in an unconfigured community build', () => {
        env.VITE_NOCLICK_LOCAL = '1';
        delete env.VITE_INBOUND_EMAIL_DOMAIN;
        expect(inboundEmailDomain()).toBeNull();
    });

    it('uses an operator-owned community domain', () => {
        env.VITE_NOCLICK_LOCAL = '1';
        env.VITE_INBOUND_EMAIL_DOMAIN = 'Mail.Automation.Example.Test ';
        expect(inboundEmailDomain()).toBe('mail.automation.example.test');
    });

    it('refuses NoClick hosted mail in a community build', () => {
        env.VITE_NOCLICK_LOCAL = '1';
        env.VITE_INBOUND_EMAIL_DOMAIN = 'noclick.app';
        expect(inboundEmailDomain()).toBeNull();
    });

    it('refuses malformed configured domains', () => {
        env.VITE_NOCLICK_LOCAL = '1';
        env.VITE_INBOUND_EMAIL_DOMAIN = 'https://mail.example.test';
        expect(inboundEmailDomain()).toBeNull();
    });
});
