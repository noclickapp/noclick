// @vitest-environment jsdom
// The WhatsApp trigger's "Only These Chats" list through the real NodeConfig and its generated schema: a
// list-valued x-dynamic-options field renders one chat picker per item (plus one for the next pick) on the
// node's existing chat loader, picking appends the chat and caches its name, and removing drops both.
import {
    act,
    cleanup,
    fireEvent,
    render,
    waitFor,
} from '@testing-library/react';
import {
    afterEach,
    beforeAll,
    beforeEach,
    describe,
    expect,
    it,
    vi,
} from 'vitest';
import { NodeConfig } from '~/components/workflow/NodeConfig';
import { WorkflowProvider } from '~/components/workflow/WorkflowContext';
import { loadNodeSchemas } from '~/utils/nodeSchemas';
import { getAutomaticTriggers } from '~/utils/workflowTriggers';

const mocks = vi.hoisted(() => ({ send: vi.fn() }));
vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: mocks.send }));
vi.mock('~/lib/analytics', () => ({
    useAnalytics: () => ({ track: vi.fn(), logActivity: vi.fn() }),
}));
vi.mock('~/hooks/useAgentCredentialsRequired', () => ({
    useAgentCredentialsRequired: () => ({
        credentialsRequired: false,
        allowUsageBased: false,
        provider: null,
    }),
}));

const GROUP = '120000000000000001@g.us';
const OTHER = '222@g.us';

const optionLoads = () =>
    mocks.send.mock.calls
        .map(([request]) => request)
        .filter((r) => r.event_name === 'workflow:node:load_options');

function renderTrigger(config: Record<string, unknown>, onChange = vi.fn()) {
    const view = render(
        <WorkflowProvider workflowId="wf-test" workflowName="Bridge">
            <NodeConfig
                nodeType="automation-whatsapp"
                nodeId="wa"
                workflowId="wf-test"
                operation="receive_message"
                config={{ operation: 'receive_message', ...config }}
                onChange={onChange}
            />
        </WorkflowProvider>
    );
    const row = (i: number) =>
        view.container.querySelector(
            `input[data-field-key="chat_ids.${i}"]`
        ) as HTMLInputElement | null;
    const lastConfig = () =>
        onChange.mock.calls.at(-1)?.[0] as Record<string, unknown>;
    return { ...view, row, onChange, lastConfig };
}

beforeAll(() => loadNodeSchemas(['automation-whatsapp']));
beforeEach(() => {
    mocks.send.mockReset();
    mocks.send.mockImplementation(async (request) =>
        request.event_name === 'workflow:node:load_options'
            ? {
                  success: true,
                  options: [
                      { value: GROUP, label: 'Book club' },
                      { value: OTHER, label: 'Team' },
                  ],
                  next_page_token: null,
              }
            : { success: true, valid: true, errors: [], options: [] }
    );
});
afterEach(cleanup);

describe('WhatsApp trigger chat allowlist', () => {
    it('shows each listed chat by name, with an empty picker for the next one', () => {
        const { row } = renderTrigger({
            chat_ids: [GROUP],
            chat_ids__label: { [GROUP]: 'Book club' },
        });
        expect(row(0)?.value).toBe('Book club');
        expect(row(1)?.value).toBe('');
        expect(row(2)).toBeNull();
    });

    it("picks from the node's chat loader and appends the chat with its name", async () => {
        const { row, lastConfig, getByText } = renderTrigger({
            chat_ids: [GROUP],
            chat_ids__label: { [GROUP]: 'Book club' },
        });
        fireEvent.focus(row(1)!);
        await waitFor(() => expect(optionLoads().length).toBeGreaterThan(0));
        expect(optionLoads().at(-1)).toMatchObject({
            node_type: 'automation-whatsapp',
            field_name: 'chat_id',
        });
        await act(async () => {
            await mocks.send.mock.results.at(-1)?.value;
        });
        fireEvent.click(getByText('Team'));
        await waitFor(() =>
            expect(lastConfig()?.chat_ids).toEqual([GROUP, OTHER])
        );
        expect(lastConfig().chat_ids__label).toEqual({
            [GROUP]: 'Book club',
            [OTHER]: 'Team',
        });
    });

    it('removes a chat and its cached name', async () => {
        const { getAllByLabelText, lastConfig } = renderTrigger({
            chat_ids: [GROUP, OTHER],
            chat_ids__label: { [GROUP]: 'Book club', [OTHER]: 'Team' },
        });
        fireEvent.click(getAllByLabelText('Remove item')[0]);
        await waitFor(() => expect(lastConfig()?.chat_ids).toEqual([OTHER]));
        expect(lastConfig().chat_ids__label).toEqual({ [OTHER]: 'Team' });
    });

    it('names the listed chats in the trigger summary', () => {
        const [trigger] = getAutomaticTriggers([
            {
                id: 'wa',
                type: 'automation-whatsapp',
                position: { x: 0, y: 0 },
                data: {
                    operation: 'receive_message',
                    config: {
                        chat_ids: [GROUP, OTHER],
                        chat_ids__label: { [GROUP]: 'Book club' },
                    },
                },
            } as never,
        ]);
        expect(trigger.params).toContainEqual({
            label: 'Only These Chats',
            value: `Book club, ${OTHER}`,
        });
    });
});
