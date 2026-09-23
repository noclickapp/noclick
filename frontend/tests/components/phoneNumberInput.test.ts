// formatPhone, the phone field's typing rules: digits without a + take the
// picked country's calling code (minus a national trunk 0), a typed +code
// names its own country, and the value handed to forms is E.164.
import { describe, expect, it } from 'vitest';
import { formatPhone } from '~/components/ui/phone-number-input';

describe('formatPhone', () => {
    it('adds the picked country code to a number typed without +', () => {
        expect(formatPhone('5504000', 'BE').text).toBe('+32 55 04 00 0');
        const full = formatPhone('470123456', 'BE');
        expect(full.text).toBe('+32 470 12 34 56');
        expect(full.e164).toBe('+32470123456');
        expect(full.country).toBe('BE');
    });

    it('drops the national trunk 0 when the code goes on', () => {
        expect(formatPhone('0470123456', 'BE').e164).toBe('+32470123456');
        expect(formatPhone('07700900123', 'GB').e164).toBe('+447700900123');
    });

    it('lets a typed + code pick the country, whatever was selected', () => {
        const uk = formatPhone('+447700900123', 'BE');
        expect(uk.country).toBe('GB');
        expect(uk.e164).toBe('+447700900123');
        // A shared code names its main country until the digits say otherwise.
        expect(formatPhone('+1', 'BE').country).toBe('US');
        expect(formatPhone('+1 416 555 0123', 'US').country).toBe('CA');
    });

    it('is empty for nothing and ignores stray characters', () => {
        expect(formatPhone('', 'BE')).toEqual({ text: '', e164: '' });
        expect(formatPhone('+1 (424) 242-1064').e164).toBe('+14242421064');
    });
});
