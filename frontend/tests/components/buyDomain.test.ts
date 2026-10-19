import { describe, expect, it } from 'vitest';
import { parseDomainQuery } from '~/hooks/useDomainPurchase';

describe('parseDomainQuery', () => {
    it('reads a bare name, with no ending', () => {
        expect(parseDomainQuery('acme')).toEqual({ name: 'acme', ending: null });
    });

    it('reads a domain however it was pasted', () => {
        expect(parseDomainQuery('  Acme.AI ')).toEqual({ name: 'acme', ending: 'ai' });
        expect(parseDomainQuery('https://www.acme.io/pricing?x=1')).toEqual({ name: 'acme', ending: 'io' });
    });

    it('joins words into one name and searches a subdomain’s parent', () => {
        expect(parseDomainQuery('Acme Labs')).toEqual({ name: 'acmelabs', ending: null });
        expect(parseDomainQuery('help.acme.com')).toEqual({ name: 'acme', ending: 'com' });
    });

    it('refuses what can’t be a domain', () => {
        expect(parseDomainQuery('')).toBeNull();
        expect(parseDomainQuery('-acme')).toBeNull();
        expect(parseDomainQuery('acme_labs')).toBeNull();
        expect(parseDomainQuery('acme.c0m')).toBeNull();
    });
});
