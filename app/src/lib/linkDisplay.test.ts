// How a reply's link reads: a raw URL short, NoClick's own link for a person named for what it does, and words the
// model chose kept as written.
import { describe, expect, it } from 'vitest';
import { linkDisplay, shortAddress } from '@/lib/linkDisplay';

const PURCHASE = 'https://noclick.com/credential/purchase/ff9f5121ba28a812cbcbc22b23334ebbaf3d9be5ba28a812cbcbc22b23334ebbaf3d9';

describe('linkDisplay', () => {
    it('names a raw capability link for what it does', () => {
        expect(linkDisplay(PURCHASE, PURCHASE)).toEqual({ kind: 'capability', label: 'Purchase link' });
        expect(linkDisplay('https://www.noclick.com/credential/provide/tok_123', 'https://www.noclick.com/credential/provide/tok_123')).toEqual({ kind: 'capability', label: 'Connect link' });
        expect(linkDisplay('https://noclick.com/approve/apr_1', 'noclick.com/approve/apr_1')).toEqual({ kind: 'capability', label: 'Approve' });
        expect(linkDisplay('https://noclick.com/b/lnk', 'https://noclick.com/b/lnk')).toEqual({ kind: 'capability', label: 'Request link' });
        expect(linkDisplay('https://noclick.com/upgrade?plan=pro', 'https://noclick.com/upgrade?plan=pro')).toEqual({ kind: 'capability', label: 'Upgrade' });
    });

    it('knows the page’s own host as NoClick’s, as a self-hosted install serves it', () => {
        expect(linkDisplay('http://localhost:5173/a/lnk', 'http://localhost:5173/a/lnk', 'localhost:5173')).toEqual({ kind: 'capability', label: 'Chat link' });
        expect(linkDisplay('http://localhost:5173/a/lnk', 'http://localhost:5173/a/lnk')).toEqual({ kind: 'short', text: 'localhost/a/lnk' });
    });

    it('shortens any other raw URL, keeping its site and trimming its long parts', () => {
        expect(linkDisplay('https://www.example.com/docs/setup', 'https://www.example.com/docs/setup')).toEqual({ kind: 'short', text: 'example.com/docs/setup' });
        expect(linkDisplay('https://noclick.com/pricing', 'https://noclick.com/pricing')).toEqual({ kind: 'short', text: 'noclick.com/pricing' });
        expect(shortAddress(new URL('https://example.com/t/ff9f5121ba28a812cbcbc22b23334ebbaf3d9'))).toBe('example.com/t/ff9f…3d9');
        expect(shortAddress(new URL('https://example.com/a?b=c'))).toBe('example.com/a…');
        expect(shortAddress(new URL(`https://docs.example.com/guides/${'setting-up/'.repeat(5)}final-step`))).toBe('docs.example.com/…/final-step');
    });

    it('keeps words the model chose, and leaves what is not a web address alone', () => {
        expect(linkDisplay(PURCHASE, 'Buy the number')).toEqual({ kind: 'text' });
        expect(linkDisplay('https://example.com/x', 'the report')).toEqual({ kind: 'text' });
        expect(linkDisplay('mailto:ana@example.com', 'mailto:ana@example.com')).toEqual({ kind: 'text' });
        expect(linkDisplay('/dashboard', '/dashboard')).toEqual({ kind: 'text' });
        expect(linkDisplay(undefined, 'anything')).toEqual({ kind: 'text' });
    });
});
