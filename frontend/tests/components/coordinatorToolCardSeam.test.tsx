// @vitest-environment jsdom
// A platform draws cards for tools only it has by what the call answered, not by a tool name (hosted: a call NoClick
// placed, whose tool is named after the number). The engine's own cards still win for their tools.
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, expect, it } from 'vitest';
import { registerToolCard, TurnCards } from '~/components/coordinator/toolCards';
import type { CoordinatorToolCall } from '~/lib/coordinatorToolCalls';

afterEach(cleanup);

const call = (tool: string, result: Record<string, unknown>): CoordinatorToolCall => ({ id: tool, tool, args: {}, result, running: false, startedAt: 0 });

it('draws a registered card for the calls it recognises, and nothing for the rest', () => {
    registerToolCard((c) => c.result?.status === 'paged', ({ call: c }) => <p>Paged {String(c.result?.who)}</p>);
    render(<TurnCards calls={[call('platform_pager_7f3a', { status: 'paged', who: 'Sam' }), call('platform_pager_7f3a', { status: 'queued' })]} />);
    expect(screen.getByText('Paged Sam')).toBeTruthy();
    expect(screen.getAllByText(/Paged/)).toHaveLength(1);
});

it('leaves the engine’s own cards to their tools', () => {
    registerToolCard(() => true, () => <p>Matched</p>);
    render(<TurnCards calls={[call('schedule_alarm', { success: false, error: 'nope' })]} />);
    expect(screen.queryByText('Matched')).toBeNull();
});
