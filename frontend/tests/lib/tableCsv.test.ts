// A table as CSV: a CSV a person brings reads field for field (quoted commas,
// line breaks and quotes included), a table's rows write back as a CSV that
// reads the same, and a download reads every page of the table, not the first.
import { afterEach, describe, expect, it, vi } from 'vitest';

const sendEventAsync = vi.fn();
vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: (event: unknown) => sendEventAsync(event) }));
const downloadText = vi.fn();
vi.mock('~/lib/download', () => ({ downloadText: (...args: unknown[]) => downloadText(...args) }));

const { csvToRows, downloadTableCsv, parseCsv, readAllRows, rowsToCsv } = await import('~/lib/tableCsv');

afterEach(() => vi.clearAllMocks());

describe('reading a CSV', () => {
    it('keeps quoted commas, line breaks and doubled quotes inside their field', () => {
        const text = '\uFEFFname,note\r\n"Ada, Countess","said ""hi""\nthen left"\r\n\r\nGrace,plain\n';
        expect(parseCsv(text)).toEqual({ headers: ['name', 'note'], rows: [['Ada, Countess', 'said "hi"\nthen left'], ['Grace', 'plain']] });
    });

    it('reads records as rows keyed by the header, numbers as numbers', () => {
        expect(csvToRows('id,name,score\n1,Alpha, 12.5 \n2,,x')).toEqual([
            { id: 1, name: 'Alpha', score: 12.5 },
            { id: 2, name: '', score: 'x' },
        ]);
    });
});

describe('writing a table as CSV', () => {
    it('writes every key a row has, in the order keys first appear, and reads back as it was', () => {
        const rows = [{ name: 'Ada, Countess', note: 'said "hi"' }, { name: 'Grace', tags: ['a', 'b'], note: null }];
        const csv = rowsToCsv(rows);
        expect(csv).toBe('name,note,tags\r\n"Ada, Countess","said ""hi""",\r\nGrace,,"[""a"",""b""]"');
        expect(parseCsv(csv)).toEqual({ headers: ['name', 'note', 'tags'], rows: [['Ada, Countess', 'said "hi"', ''], ['Grace', '', '["a","b"]']] });
    });

    it('reads every page of a table before it downloads', async () => {
        const all = Array.from({ length: 25_000 }, (_, i) => ({ id: i }));
        sendEventAsync.mockImplementation(async (event: { resource_id: string; limit: number; offset: number }) => ({
            rows: all.slice(event.offset, event.offset + event.limit).map((data) => ({ data })),
            total_count: all.length,
        }));
        expect(await readAllRows('res_1')).toHaveLength(25_000);
        expect(sendEventAsync.mock.calls.map(([e]) => [e.resource_id, e.offset, e.limit])).toEqual([
            ['res_1', 0, 10_000],
            ['res_1', 10_000, 10_000],
            ['res_1', 20_000, 10_000],
        ]);
        await downloadTableCsv('res_1', 'leads');
        const [csv, filename, type] = downloadText.mock.calls[0];
        expect(filename).toBe('leads.csv');
        expect(type).toBe('text/csv;charset=utf-8');
        expect((csv as string).split('\r\n')).toHaveLength(25_001);
    });
});
