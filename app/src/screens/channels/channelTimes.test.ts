// The clock beside a grouped message: its hour and minute alone, in the reader's own 12- or 24-hour clock.
import { describe, expect, it } from 'vitest';
import { clockLabel } from './MessageList';

// 21:29 and 00:05 local time, whatever zone the test runs in.
const at = (h: number, m: number) => new Date(2026, 10, 11, h, m).toISOString();

describe('the gutter clock', () => {
    it('drops AM and PM on a 12-hour clock, wherever the locale writes them', () => {
        expect(clockLabel(at(21, 29), 'en-US')).toBe('9:29');
        expect(clockLabel(at(12, 59), 'en-US')).toBe('12:59');
        expect(clockLabel(at(21, 29), 'ko-KR')).toBe('9:29');
    });

    it('keeps a 24-hour clock as it is', () => {
        expect(clockLabel(at(21, 29), 'en-GB')).toBe('21:29');
        expect(clockLabel(at(0, 5), 'de-DE')).toBe(new Date(at(0, 5)).toLocaleTimeString('de-DE', { hour: 'numeric', minute: '2-digit' }));
    });
});
