// Which texting app the sidebar offers first.
import { describe, expect, it } from 'vitest';
import { preferredTextApp } from '~/components/shell/textApp';

const MAC = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15';
const ANDROID = 'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Mobile Safari/537.36';

describe('preferredTextApp', () => {
    it('offers iMessage first where it outweighs WhatsApp', () => {
        for (const country of ['US', 'CA', 'AU', 'JP', 'us']) expect(preferredTextApp(country, MAC)).toBe('imessage');
    });

    it('offers WhatsApp everywhere else, and when the country is unknown', () => {
        for (const country of ['GB', 'IN', 'BR', 'DE', 'MX', undefined]) expect(preferredTextApp(country, MAC)).toBe('whatsapp');
    });

    it('never offers iMessage first to an Android phone', () => {
        expect(preferredTextApp('US', ANDROID)).toBe('whatsapp');
    });
});
