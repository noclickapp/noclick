// Machines' rows: a NoClick machine says how long it's been up and who's on it, where it runs as a place and its price
// a month; one held until NoClick approves the company says whose approval it waits for; a computer of yours is
// online with its agents, named as your Mac.
import { describe, expect, it } from 'vitest';
import { placeItem } from './knowledgeItems';
import type { Compute, OwnComputer } from './knowledge';

const NOW = Date.parse('2026-11-10T10:00:00.000Z');
const machine = (over: Partial<Compute> = {}): Compute => ({
    kind: 'machine',
    id: 'm-1',
    name: 'ops-box',
    status: 'running',
    userId: null,
    region: 'us-east',
    cpu: 2,
    memoryGb: 4,
    startedAt: null,
    usdPerHour: 0.04,
    usdPerMonth: 31.2,
    spentUsdToday: null,
    running: [],
    ...over,
});

describe('a machine’s row', () => {
    it('says how long it’s been up and who’s on it, in a place’s name, priced a month', () => {
        const row = placeItem(
            machine(),
            undefined,
            {
                agents: ['Scout', 'Ledger'],
                size: 'small',
                startedAt: new Date(NOW - 12 * 24 * 3600_000).toISOString(),
                status: 'running',
            },
            NOW
        );
        expect(row).toMatchObject({
            title: 'ops-box',
            subtitle: 'Up 12 days · Scout, Ledger',
            where: 'US East',
            price: { usd: 31.2, per: 'month' },
        });
    });

    it('says a held machine waits for NoClick to approve the company, charging nothing before', () => {
        const row = placeItem(
            machine({
                status: 'awaiting_approval',
                region: 'eu',
                usdPerMonth: 8.39,
            }),
            undefined,
            {
                size: 'small',
                status: 'awaiting_approval',
                company: 'Example Commerce',
            },
            NOW
        );
        expect(row.subtitle).toBe(
            'Waiting for NoClick to approve Example Commerce · Small'
        );
        expect(row.pending).toBe(
            'It starts the moment NoClick approves Example Commerce. Nothing is charged until then.'
        );
        expect(row.where).toBe('Europe');
    });

    it('names your own Mac and its agents', () => {
        const mac: OwnComputer = {
            kind: 'own',
            id: 'm-own',
            name: 'river-mbp',
            status: 'running',
            os: 'Ubuntu 24.04.3 LTS (VM on macOS 15.1)',
            hostname: 'river-mbp',
            lastSeenAt: null,
            cpu: 10,
            memoryGb: 16,
            conversationsAtOnce: 4,
            agentShare: 0.75,
            agentShareFixed: true,
            appTesting: 'ask_first',
            pairing: null,
            agentsEnabled: true,
            createdAt: null,
        };
        expect(
            placeItem(mac, undefined, { agents: ['Pixel'] }, NOW)
        ).toMatchObject({
            subtitle: 'Online · Pixel',
            where: 'Your Mac',
            price: null,
        });
    });
});
