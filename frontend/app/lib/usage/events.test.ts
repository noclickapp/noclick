// Unit tests for the pure usage:event merge helpers. These pin the behavior
// that used to live (three times) inside setState updaters: correct bucket
// merge/insert, no input mutation (StrictMode double-invocation safety), and
// the workspace scope filter that mirrors the backend query.

import { describe, it, expect } from 'vitest';
import type { UsageEventUpdateEvent } from '~/types/socket-events.generated';
import {
    applyEventToUsageData,
    eventMatchesLogFilters,
    eventMatchesWorkspace,
    eventWithinDayRange,
    prependUsageLog,
    usageEventDayKey,
    utcDayKey,
} from './events';
import type { UsageData, UsageLogsData } from './types';

const T_2026_07_03_NOON_UTC = Date.UTC(2026, 6, 3, 12, 0, 0) / 1000;

function makeEvent(
    overrides: Partial<UsageEventUpdateEvent> = {}
): UsageEventUpdateEvent {
    return {
        usage_type: 'ai_usage',
        usage_subtype: 'gpt-4o',
        total_cost: 0.5,
        quantity: 1000,
        unit_type: 'tokens',
        user_resource: false,
        timestamp: T_2026_07_03_NOON_UTC,
        ...overrides,
    };
}

function makeData(overrides: Partial<UsageData> = {}): UsageData {
    return {
        total_cost: 1.0,
        usage_by_type: { ai_usage: 1.0 },
        usage_by_subtype: { 'gpt-4o': 1.0 },
        units_by_subtype: { 'gpt-4o': 'tokens' },
        time_series: [
            {
                date: '2026-07-03',
                total_cost: 1.0,
                by_type: { ai_usage: 1.0 },
                by_subtype: { 'gpt-4o': 1.0 },
                tokens_by_subtype: { 'gpt-4o': 2000 },
            },
        ],
        period_start: null,
        period_end: null,
        ...overrides,
    };
}

describe('usageEventDayKey', () => {
    it('buckets by UTC day from the event timestamp', () => {
        expect(usageEventDayKey(makeEvent())).toBe('2026-07-03');
        // 23:30 UTC stays on the UTC day regardless of the host timezone.
        expect(
            usageEventDayKey(
                makeEvent({ timestamp: Date.UTC(2026, 6, 3, 23, 30) / 1000 })
            )
        ).toBe('2026-07-03');
    });

    it('falls back to nowMs when the event has no timestamp', () => {
        const now = Date.UTC(2026, 6, 4, 1, 0);
        expect(usageEventDayKey(makeEvent({ timestamp: null }), now)).toBe(
            '2026-07-04'
        );
    });
});

describe('applyEventToUsageData', () => {
    it('merges into an existing day bucket and all aggregates', () => {
        const next = applyEventToUsageData(makeData(), makeEvent());
        expect(next.total_cost).toBeCloseTo(1.5);
        expect(next.usage_by_type.ai_usage).toBeCloseTo(1.5);
        expect(next.usage_by_subtype['gpt-4o']).toBeCloseTo(1.5);
        expect(next.time_series).toHaveLength(1);
        expect(next.time_series[0].total_cost).toBeCloseTo(1.5);
        expect(next.time_series[0].by_subtype['gpt-4o']).toBeCloseTo(1.5);
        expect(next.time_series[0].tokens_by_subtype['gpt-4o']).toBe(3000);
    });

    it('inserts a new day bucket in sorted position', () => {
        const next = applyEventToUsageData(
            makeData(),
            makeEvent({ timestamp: Date.UTC(2026, 6, 1, 8, 0) / 1000 })
        );
        expect(next.time_series.map((e) => e.date)).toEqual([
            '2026-07-01',
            '2026-07-03',
        ]);
        expect(next.time_series[0].by_type.ai_usage).toBeCloseTo(0.5);
    });

    it('tracks a brand-new subtype including its unit', () => {
        const next = applyEventToUsageData(
            makeData(),
            makeEvent({
                usage_type: 'cpu_usage',
                usage_subtype: 'custom/compute',
                unit_type: 'seconds',
                quantity: 30,
            })
        );
        expect(next.usage_by_subtype['custom/compute']).toBeCloseTo(0.5);
        expect(next.units_by_subtype?.['custom/compute']).toBe('seconds');
        // The aggregated unit for an existing subtype is never overwritten.
        expect(next.units_by_subtype?.['gpt-4o']).toBe('tokens');
    });

    it('does not mutate its input (safe under StrictMode double-invocation)', () => {
        const prev = makeData();
        const snapshot = JSON.parse(JSON.stringify(prev));
        applyEventToUsageData(prev, makeEvent());
        expect(prev).toEqual(snapshot);
    });

    it('is deterministic: applying twice from the same base gives the same result', () => {
        const prev = makeData();
        const a = applyEventToUsageData(prev, makeEvent());
        const b = applyEventToUsageData(prev, makeEvent());
        expect(a).toEqual(b);
    });

    it('handles cached entries that predate tokens_by_subtype', () => {
        const legacy = makeData();
        delete (
            legacy.time_series[0] as Partial<(typeof legacy.time_series)[0]>
        ).tokens_by_subtype;
        const next = applyEventToUsageData(legacy, makeEvent());
        expect(next.time_series[0].tokens_by_subtype['gpt-4o']).toBe(1000);
    });
});

describe('prependUsageLog', () => {
    it('creates the list when there is none', () => {
        const next = prependUsageLog(null, makeEvent());
        expect(next.logs).toHaveLength(1);
        expect(next.logs[0].model).toBe('gpt-4o');
        expect(next.logs[0].unit_type).toBe('tokens');
        expect(next.count).toBe(1);
    });

    it('prepends, caps the visible list, and keeps counting past the cap', () => {
        let data: UsageLogsData = { logs: [], count: 0 };
        for (let i = 0; i < 25; i++) {
            data = prependUsageLog(data, makeEvent({ total_cost: i }));
        }
        expect(data.logs).toHaveLength(20);
        expect(data.logs[0].cost).toBe(24); // newest first
        expect(data.count).toBe(25);
    });

    it('null cap never truncates a paginated list, and has_more survives', () => {
        let data: UsageLogsData = { logs: [], count: 0, has_more: true };
        for (let i = 0; i < 25; i++) {
            data = prependUsageLog(data, makeEvent({ total_cost: i }), null);
        }
        expect(data.logs).toHaveLength(25);
        expect(data.has_more).toBe(true);
    });
});

describe('eventMatchesLogFilters', () => {
    it('filters by category and case-insensitive subtype substring', () => {
        const event = makeEvent(); // ai_usage / gpt-4o
        expect(
            eventMatchesLogFilters(event, { search: '', usageType: null })
        ).toBe(true);
        expect(
            eventMatchesLogFilters(event, { search: '', usageType: 'ai_usage' })
        ).toBe(true);
        expect(
            eventMatchesLogFilters(event, {
                search: '',
                usageType: 'cpu_usage',
            })
        ).toBe(false);
        expect(
            eventMatchesLogFilters(event, { search: 'GPT', usageType: null })
        ).toBe(true);
        expect(
            eventMatchesLogFilters(event, { search: 'claude', usageType: null })
        ).toBe(false);
        expect(
            eventMatchesLogFilters(event, { search: '  ', usageType: null })
        ).toBe(true); // whitespace = no filter
    });
});

describe('eventMatchesWorkspace', () => {
    it('org view matches only the org tag', () => {
        expect(
            eventMatchesWorkspace(
                makeEvent({ organization_id: 'org1' }),
                'org1',
                null
            )
        ).toBe(true);
        expect(
            eventMatchesWorkspace(
                makeEvent({ organization_id: 'org2' }),
                'org1',
                null
            )
        ).toBe(false);
        expect(
            eventMatchesWorkspace(
                makeEvent({ organization_id: null }),
                'org1',
                null
            )
        ).toBe(false);
    });

    it('personal view matches the charged pool owner', () => {
        expect(
            eventMatchesWorkspace(
                makeEvent({ billing_user_id: 'me' }),
                null,
                'me'
            )
        ).toBe(true);
        expect(
            eventMatchesWorkspace(
                makeEvent({ billing_user_id: 'owner' }),
                null,
                'me'
            )
        ).toBe(false);
        // Unknown pool (first read not landed) counts the event; the fetch reconciles.
        expect(
            eventMatchesWorkspace(
                makeEvent({ billing_user_id: 'owner' }),
                null,
                null
            )
        ).toBe(true);
        expect(
            eventMatchesWorkspace(
                makeEvent({ billing_user_id: null }),
                null,
                'me'
            )
        ).toBe(true);
    });
});

describe('eventWithinDayRange', () => {
    it('is day-granular in UTC', () => {
        const from = new Date(Date.UTC(2026, 6, 1));
        const to = new Date(Date.UTC(2026, 6, 3));
        expect(eventWithinDayRange(makeEvent(), from, to)).toBe(true);
        expect(
            eventWithinDayRange(
                makeEvent({ timestamp: Date.UTC(2026, 6, 4, 0, 30) / 1000 }),
                from,
                to
            )
        ).toBe(false);
    });
});

describe('utcDayKey', () => {
    it('uses the UTC calendar date', () => {
        expect(utcDayKey(new Date(Date.UTC(2026, 6, 3, 23, 59)))).toBe(
            '2026-07-03'
        );
    });
});
