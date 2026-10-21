// How a search finds something by name: its own name first, a word people use for it nearly as well, where it lives
// only alongside other words, and a line about it last.
import { describe, expect, it } from 'vitest';
import { scoreNamed, type Named } from '~/lib/fuzzyRank';

const domains = { label: 'Domains', context: 'Resources', keywords: 'domain dns domain names', about: 'Domains for your websites, registered in your name.' };
const apiKeys = { label: 'API keys', context: 'Developers', keywords: 'api key keys secret key' };
const order = (query: string, items: Named[]) =>
    items
        .map((item) => ({ item, score: scoreNamed(query, item) }))
        .filter((x) => x.score !== null)
        .sort((a, b) => a.score! - b.score!)
        .map((x) => x.item.label);

describe('scoreNamed', () => {
    it('ranks a name exactly, then its start, then the start of one of its words, then anywhere in it', () => {
        const items = [{ label: 'Buy a domain' }, { label: 'Domains' }, { label: 'Subdomains' }, { label: 'Domain' }];
        expect(order('domain', items)).toEqual(['Domain', 'Domains', 'Buy a domain', 'Subdomains']);
    });

    it('takes a keyword the query is nearly as a name, ahead of a name it only starts', () => {
        expect(order('dns', [domains, { label: 'DNS records guide' }])).toEqual(['Domains', 'DNS records guide']);
        expect(order('api key', [apiKeys, { label: 'Developer', keywords: 'api key token sdk' }])).toEqual(['API keys', 'Developer']);
    });

    it('never takes one letter for a word', () => {
        expect(scoreNamed('a', { label: 'Zebra', keywords: 'a b c' })).toBeGreaterThan(scoreNamed('a', { label: 'Apples' })!);
    });

    it('matches where a thing lives only beside other words', () => {
        expect(scoreNamed('resources', domains)).toBeNull();
        expect(scoreNamed('resources domains', domains)).not.toBeNull();
        expect(scoreNamed('resources dns', domains)).not.toBeNull();
    });

    it('reads its about line on whole words, for three letters or more', () => {
        expect(scoreNamed('websites', domains)).not.toBeNull();
        expect(scoreNamed('ebsites', domains)).toBeNull();
        expect(scoreNamed('yo', { label: 'Zebra', about: 'your thing' })).toBeNull();
    });

    it('ignores a leading "go to"', () => {
        expect(scoreNamed('go to domains', domains)).toBe(scoreNamed('domains', domains));
        expect(scoreNamed('goto domains', domains)).toBe(scoreNamed('domains', domains));
    });
});
