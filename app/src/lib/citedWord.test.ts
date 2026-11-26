// A call's result names whose word it acted on only where it cited one: the step's row reads that, and nothing else.
import { describe, expect, it } from 'vitest';
import { citedWord } from './citedWord';

describe('citedWord', () => {
    it('reads a cited call, as an object or the JSON a preview keeps, and nothing else', () => {
        const authority = { basis: 'cited', author: 'Ana', quote: 'publish the pricing page', why: 'She asked for it.', message: 'channel_message:m1' };
        expect(citedWord({ success: true, authority })).toEqual({ author: 'Ana', quote: 'publish the pricing page', why: 'She asked for it.' });
        expect(citedWord(JSON.stringify({ authority }))).toEqual({ author: 'Ana', quote: 'publish the pricing page', why: 'She asked for it.' });
        expect(citedWord({ authority: { basis: 'floor' } })).toBeNull();
        expect(citedWord({ authority: { basis: 'held', refused: 'it cites nobody who may' } })).toBeNull();
        expect(citedWord('not json')).toBeNull();
        expect(citedWord(null)).toBeNull();
    });
});
