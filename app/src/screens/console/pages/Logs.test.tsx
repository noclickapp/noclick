// @vitest-environment happy-dom
// The tool-call log names the connection a call ran on as the account names it, falling back to its credential's id
// where the call has no name for it, and its agent stays in Source.
import { cleanup, render } from '@testing-library/react';
import { afterEach, expect, it } from 'vitest';
import { ToolCall } from 'noclick';
import { toolCallColumns } from './Logs';
import type { ConsoleNames } from './OperationDrawer';

afterEach(cleanup);

const NAMES: ConsoleNames = {
    agent: (id) => (id === 'a-1' ? { name: 'Support', userId: null } : null),
    key: () => null,
    agentHandles: [],
    userIds: [],
    keyPrefixes: [],
};

const call = (raw: Record<string, unknown>) => new ToolCall({ id: 'tc-1', tool_name: 'gmail.send_email', status: 'success', agent_id: 'a-1', ...raw });
const cell = (id: string, c: ToolCall) => {
    const column = toolCallColumns(NAMES).find((col) => col.id === id)!;
    return render(<>{column.cell(c)}</>).container;
};

it('names the connection a call ran on, else shows its credential’s id', () => {
    expect(toolCallColumns(NAMES).find((col) => col.id === 'connection')?.header).toBe('Connection');
    expect(cell('connection', call({ credential_id: 'cred-1', connection: 'work-gmail' })).textContent).toBe('work-gmail');

    const unnamed = cell('connection', call({ credential_id: 'cred-1', connection: null }));
    expect(unnamed.querySelector('[title="cred-1"]')?.textContent).toBe('cred-1');

    expect(cell('connection', call({})).textContent).toBe('—');
});

it('keeps the agent in Source', () => {
    expect(cell('source', call({ connection: 'work-gmail' })).textContent).toBe('Support');
});
