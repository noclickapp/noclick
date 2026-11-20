// @vitest-environment happy-dom
// The usage page's parts over a read where nobody is billed: the headline and its range, the period day by day, and
// "Where it goes", which opens a service onto what inside it cost the most and climbs back with Back.
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { MotionGlobalConfig } from 'framer-motion';
import { useState } from 'react';
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { DayColumns } from './charts';
import { NO_DRILL, deriveView, dimensionsFor, toSnapshot, type Drill } from './derive';
import { WhereItGoes } from './drill';
import { Hero } from './parts';
import type { UsagePageData } from './types';

// The reader's days, in one zone whatever the machine's.
vi.hoisted(() => {
    process.env.TZ = 'UTC';
});

const ME = 'u-1';
const WF = 'wf-1';
const SONNET = 'openrouter/anthropic/claude-sonnet-4.6';
const MINI = 'openrouter/openai/gpt-4o-mini';

function group(day: string, subtype: string, usd: number) {
    const ai = subtype.startsWith('openrouter/');
    return {
        current: true,
        day,
        created_at: `${day}T09:00:00Z`,
        k: `${subtype}|${day}`,
        user_id: ME,
        usage_type: ai ? 'ai_usage' : 'api_usage',
        usage_subtype: subtype,
        unit_type: ai ? 'tokens' : 'requests',
        user_resource: false,
        n: 2,
        quantity: ai ? 20000 : 2,
        total_cost: usd,
        prompt_tokens: 0,
        completion_tokens: 0,
        workflow_id: WF,
        node_id: 'agent-1',
    };
}

function read(groups: ReturnType<typeof group>[]): UsagePageData {
    return {
        now: '2026-10-16T15:20:00Z',
        account: { id: ME },
        period: { window_start: '2026-10-01T00:00:00Z', window_end: '2026-11-01T00:00:00Z', previous_start: '2026-09-01T00:00:00Z' },
        billing: null,
        groups: groups as UsagePageData['groups'],
        directory: { workflows: { [WF]: { name: 'Inbox triage' } }, agents: { [`${WF}:agent-1`]: { name: 'Support agent' } }, people: { [ME]: { name: 'Ada' } } },
        charges: { rows: [], runs: {}, next: null },
    };
}

const BUSY = read([
    group('2026-10-14', SONNET, 3),
    group('2026-10-15', SONNET, 2),
    group('2026-10-15', MINI, 1),
    group('2026-10-15', 'exa/search_api', 0.5),
]);

beforeAll(() => {
    // The days draw at a laptop's width.
    globalThis.ResizeObserver = class {
        constructor(private readonly cb: ResizeObserverCallback) {}
        observe(target: Element) {
            this.cb([{ target, contentRect: { width: 760, height: 210 } } as unknown as ResizeObserverEntry], this as unknown as ResizeObserver);
        }
        unobserve() {}
        disconnect() {}
    } as unknown as typeof ResizeObserver;
    MotionGlobalConfig.skipAnimations = true;
});

afterEach(cleanup);

describe('the headline', () => {
    it('says what the period comes to at this pace, and what was spent so far', () => {
        render(<Hero view={deriveView(toSnapshot(BUSY))} />);
        expect(screen.getByText(/projected at the current pace, Oct 1 to Oct 31/)).toBeTruthy();
        expect(screen.getByText(/\$6\.50 so far|anywhere from/)).toBeTruthy();
    });

    it('says nothing was spent yet on a period with no charges', () => {
        render(<Hero view={deriveView(toSnapshot(read([])))} />);
        expect(screen.getByText('nothing spent yet, Oct 1 to Oct 31')).toBeTruthy();
    });
});

describe('the days', () => {
    it('draws the period and picks a day that has passed', () => {
        const onSelect = vi.fn();
        render(<DayColumns view={deriveView(toSnapshot(BUSY))} ink="services" projection="ghost" height={210} selected={null} onSelect={onSelect} />);
        expect(screen.getByRole('img', { name: 'Spend each day, Oct 1 to Oct 31' })).toBeTruthy();
        fireEvent.click(document.querySelector('rect[data-day="2026-10-14"]')!);
        expect(onSelect).toHaveBeenCalledWith('2026-10-14');
    });
});

describe('where it goes', () => {
    function Drilled() {
        const view = deriveView(toSnapshot(BUSY));
        const [drill, setDrill] = useState<Drill>(NO_DRILL);
        return <WhereItGoes view={view} root="service" dims={dimensionsFor(view)} onRoot={() => undefined} drill={drill} onDrill={setDrill} style="stack" ink="services" />;
    }

    it('opens a service onto its models and climbs back', () => {
        render(<Drilled />);
        const section = screen.getByRole('region', { name: 'Where it goes' });
        expect(within(section).getByText('AI models')).toBeTruthy();
        fireEvent.click(within(section).getByText('AI models'));
        expect(within(section).getByText('Claude Sonnet 4.6')).toBeTruthy();
        expect(within(section).getByText('GPT-4o Mini')).toBeTruthy();
        fireEvent.click(within(section).getByRole('button', { name: 'Back' }));
        expect(within(section).getByText('Tools and data')).toBeTruthy();
    });
});
