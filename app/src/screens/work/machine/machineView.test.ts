// What a machine's page reads into its view and judges from it: a NoClick machine priced a month and a day (never an
// hour) in a place's name, your own Mac named as yours, each state's meaning for its agents, and the health verdict
// with its fix (a bigger size on a NoClick machine, fewer agents at once on your own), bars and all.
import { describe, expect, it } from 'vitest';
import { ownMac, runningNoClick } from './fixtures/machineWorld';
import {
    barsOf,
    kindLine,
    ownDevice,
    perDay,
    priceLine,
    stateInfo,
    toMachineView,
    upLine,
    verdictOf,
    workingIds,
} from './machineView';

const NOW = Date.parse('2026-11-10T10:00:00.000Z');
const opsBox = (over: Record<string, unknown> = {}) =>
    toMachineView({
        object: 'machine',
        id: 'm-1',
        name: 'ops-box',
        kind: 'noclick',
        status: 'running',
        size: 'small',
        region: 'us-east',
        cpu: 2,
        memory_gb: 4,
        disk_gb: 80,
        monthly_usd: 31.2,
        ...runningNoClick(NOW),
        ...over,
    });

describe('the view', () => {
    it('reads what the page shows from GET /v1/machines/{id}', () => {
        const m = opsBox({
            working_count: 1,
            agent_states: [
                { agent_id: 'a-1', working: true },
                { agent_id: 'a-2', working: false },
            ],
            pending: null,
        });
        expect(m.spentUsdThisMonth).toBe(16.64);
        expect(m.workingCount).toBe(1);
        expect(m.health).toMatchObject({
            cpuPercent: 38,
            memoryUsedGb: 2.6,
            memoryTotalGb: 4,
            diskUsedGb: 31,
            diskTotalGb: 80,
        });
        expect(workingIds(m)).toEqual(['a-1']);
        expect(kindLine(m)).toBe('NoClick machine · Small · US East');
        expect(upLine(m, NOW)).toBe('Up 12 days');
    });

    it('prices a machine a month and a day, never an hour', () => {
        expect(perDay(31.2)).toBe('$1.04 a day');
        expect(priceLine(8.39)).toBe(
            'That’s $0.28 a day, from the day it starts until you delete it. Stopping it doesn’t stop the charge.'
        );
    });

    it('names your own computer as yours: a Mac by its macOS, a PC through WSL', () => {
        expect(kindLine(toMachineView(ownMac(NOW)))).toBe(
            'Your Mac · macOS 15'
        );
        expect(ownDevice('Ubuntu 24.04 LTS (WSL on Windows)')).toEqual({
            what: 'PC',
            system: 'Windows',
        });
        expect(ownDevice('Ubuntu 24.04 LTS')).toEqual({
            what: 'computer',
            system: 'Ubuntu 24.04 LTS',
        });
    });

    it('carries app testing only where the API says it', () => {
        expect(toMachineView(ownMac(NOW)).appTesting).toBe('ask_first');
        expect(
            toMachineView({ id: 'm', kind: 'own', status: 'running' })
                .appTesting
        ).toBeNull();
    });
});

describe('what each state means for its agents', () => {
    it('says a stopped machine is still charged, with Start as its action', () => {
        expect(stateInfo(opsBox({ status: 'stopped' }))).toEqual({
            tone: 'off',
            label: 'Stopped',
            meaning:
                'Agents can’t work on it until it starts again. It’s still charged $1.04 a day.',
            action: 'start',
        });
    });

    it('says a resize waits for the turns on it, or moves it to a fresh machine', () => {
        expect(
            stateInfo(
                opsBox({
                    status: 'updating',
                    pending: { size: 'large', move: false },
                })
            ).meaning
        ).toBe(
            'Becomes Large once the turns on it now end. Agents carry on until then.'
        );
        expect(
            stateInfo(
                opsBox({
                    status: 'updating',
                    pending: { size: 'small', move: true },
                })
            ).meaning
        ).toMatch(/^Moving to a fresh Small machine/);
    });

    it('says a held machine starts once NoClick approves the company, charging nothing before', () => {
        expect(
            stateInfo(
                opsBox({ status: 'awaiting_approval' }),
                'Example Commerce'
            )
        ).toMatchObject({
            label: 'Waiting for approval',
            meaning:
                'It starts the moment NoClick approves Example Commerce. Nothing is charged until then.',
        });
    });

    it('calls your own computer online, or waiting to connect while it pairs', () => {
        expect(stateInfo(toMachineView(ownMac(NOW))).label).toBe('Online');
        expect(
            stateInfo(toMachineView(ownMac(NOW, { status: 'provisioning' })))
                .label
        ).toBe('Waiting to connect');
    });
});

describe('the health verdict', () => {
    it('reads plenty of room when nothing is near full', () => {
        expect(verdictOf(opsBox(), NOW)).toEqual({
            tone: 'ok',
            text: 'Plenty of room. Agents aren’t waiting on it.',
        });
    });

    it('says a NoClick machine working hard needs a bigger size, your own fewer agents at once', () => {
        const hard = {
            health: {
                cpus: 2,
                load_1m: 1.9,
                cpu_percent: 60,
                memory_used_gb: 3.8,
                memory_total_gb: 4,
                disk_used_gb: 31,
                disk_total_gb: 80,
            },
        };
        expect(verdictOf(opsBox(hard), NOW)).toEqual({
            tone: 'bad',
            text: 'Working hard: memory is nearly full, so agents may slow down.',
            fix: { action: 'resize', label: 'A bigger size would help' },
        });
        // Your own Mac's agents may use three quarters of its 16 GB: 11.5 GB of 12 is nearly full.
        const mac = toMachineView(
            ownMac(NOW, {
                health: {
                    cpus: 10,
                    load_1m: 3,
                    cpu_percent: 30,
                    memory_used_gb: 11.5,
                    memory_total_gb: 16,
                    disk_used_gb: 18,
                    disk_total_gb: 64,
                },
            })
        );
        expect(verdictOf(mac, NOW).fix).toEqual({
            action: 'settings',
            label: 'Fewer agents at once would help',
        });
    });

    it('points a nearly full disk at its files', () => {
        expect(
            verdictOf(
                opsBox({
                    health: {
                        cpus: 2,
                        load_1m: 0.2,
                        cpu_percent: 10,
                        memory_used_gb: 1,
                        memory_total_gb: 4,
                        disk_used_gb: 74,
                        disk_total_gb: 80,
                    },
                }),
                NOW
            )
        ).toEqual({
            tone: 'bad',
            text: 'Its disk is nearly full.',
            fix: { action: 'files', label: 'See what’s using it' },
        });
    });

    it('has nothing to read while it isn’t running, and says when an offline one last checked in', () => {
        expect(verdictOf(opsBox({ status: 'stopped' }), NOW).text).toBe(
            'Nothing to read while it isn’t running.'
        );
        expect(
            verdictOf(
                toMachineView(
                    ownMac(NOW, {
                        status: 'offline',
                        last_seen_at: new Date(
                            NOW - 2 * 3600_000
                        ).toISOString(),
                    })
                ),
                NOW
            ).text
        ).toBe('Last checked in 2 hours ago. Nothing new until it’s back.');
    });

    it('draws three bars, each with a plain word and its numbers', () => {
        const m = opsBox();
        expect(
            barsOf(m, m.health!).map((b) => [b.label, b.word, b.numbers])
        ).toEqual([
            ['Processors', 'Steady', '38% busy'],
            ['Memory', 'Getting full', '2.6 of 4 GB'],
            ['Disk', 'Plenty free', '31 of 80 GB used'],
        ]);
        const mac = toMachineView(ownMac(NOW));
        expect(barsOf(mac, mac.health!)[1].numbers).toBe(
            '3.1 of the 12 GB agents may use'
        );
    });
});
