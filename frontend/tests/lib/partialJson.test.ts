import { describe, expect, it } from 'vitest';
import { parsePartialJson } from '~/lib/partialJson';

describe('parsePartialJson', () => {
    it('reads whole JSON as JSON.parse does', () => {
        const src = '{"a": 1, "b": [true, null, "x\\"y"], "c": {"d": -2.5e3}}';
        expect(parsePartialJson(src)).toEqual(JSON.parse(src));
    });

    it('keeps every entry that arrived whole and drops the one the cut went through', () => {
        expect(parsePartialJson('{"job_id": "j1", "workflow_id": "w1", "note": "The builder owns th')).toEqual({ job_id: 'j1', workflow_id: 'w1' });
    });

    it('never passes a cut string off as a whole one', () => {
        expect(parsePartialJson('{"url": "https://noclick.com/pay/12')).toEqual({});
    });

    it('drops a number that may have lost digits', () => {
        expect(parsePartialJson('{"price_usd": 25, "credits": 12')).toEqual({ price_usd: 25 });
    });

    it('keeps the finished part of a nested object the cut went through', () => {
        expect(parsePartialJson('{"success": true, "job": {"job_id": "j", "agent_name": "Inbox", "message": "Plea')).toEqual({
            success: true,
            job: { job_id: 'j', agent_name: 'Inbox' },
        });
    });

    it('keeps the finished items of a cut array', () => {
        expect(parsePartialJson('{"images": ["https://a/1.png", "https://a/2')).toEqual({ images: ['https://a/1.png'] });
    });

    it('stops at a key the cut went through', () => {
        expect(parsePartialJson('{"a": 1, "lon')).toEqual({ a: 1 });
        expect(parsePartialJson('{"a": 1, "long": ')).toEqual({ a: 1 });
    });

    it('drops a literal the cut went through', () => {
        expect(parsePartialJson('{"a": tr')).toEqual({});
    });

    it('answers undefined for text that is not JSON', () => {
        expect(parsePartialJson('Error: something broke')).toBeUndefined();
        expect(parsePartialJson('')).toBeUndefined();
    });
});
