import { describe, expect, it } from 'vitest';
import { decodeLegacyHtmlEntities } from './legacyConfigParsing';

describe('decodeLegacyHtmlEntities', () => {
    it('decodes one layer of legacy HTML entities', () => {
        expect(
            decodeLegacyHtmlEntities(
                '[{&quot;name&quot;:&quot;A &amp; B &lt; C &gt; D&quot;}]'
            )
        ).toBe('[{"name":"A & B < C > D"}]');
    });

    it('does not double-decode nested entities', () => {
        expect(decodeLegacyHtmlEntities('&amp;quot;')).toBe('&quot;');
    });
});
