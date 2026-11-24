// Moments of an agent's conversation as the fake /v1 serves them: a coding agent mid-turn with yesterday's fix behind it
// (the lab's busy scene), the same agent waiting for approval, and a question. Shared by the tests and a local preview,
// each built from the platform's own wire shapes (history messages, kept steps, live events).
type Json = Record<string, unknown>;
import type { LiveEvent } from './workAgent';

const at = (daysAgo: number, h: number, m: number) => {
    const d = new Date();
    d.setDate(d.getDate() - daysAgo);
    d.setHours(h, m, 0, 0);
    return d.toISOString();
};

const step = (id: string, kind: string, fields: Json, when: string): Json => ({ id, source: 'harness', kind, tool: kind === 'command' ? 'shell' : kind, created_at: when, ...fields });

const CONNECTIONS_DIFF = `@@ -18,7 +18,7 @@ export default async function ConnectionsPage() {
   const connections = await listConnections();
   const ids = connections.map((c) => c.id);
-  const statuses = await Promise.all(ids.map(getStatus));
+  const statuses = await getStatuses(ids);
   return <ConnectionList connections={connections} statuses={statuses} />;
`;

/** Yesterday's fix and this morning's finding, as the conversation's history keeps them. */
export function busyHistory(): Json[] {
    return [
        { id: 'm1', role: 'user', text: 'Why is the Wirefern dashboard slow to load connections?', created_at: at(1, 18, 40), via: 'whatsapp', operation_id: 'op-y1', author: { type: 'account', id: null, name: 'Rowan Hale' } },
        {
            id: 'm2',
            role: 'assistant',
            text: 'Found it. The connections page asked for each connection’s status one at a time, so 40 connections meant 40 round trips. It now asks once for all of them, and the page loads in 0.4s instead of 6s.',
            created_at: at(1, 18, 52),
            operation_id: 'op-y1',
            tool_calls: [
                step('c1', 'search', { query: 'connection status' }, at(1, 18, 41)),
                step('c2', 'read', { path: 'web/app/connections/page.tsx' }, at(1, 18, 41)),
                step('c3', 'read', { path: 'api/routes/connections.py' }, at(1, 18, 42)),
                step('c4', 'edit', { path: 'web/app/connections/page.tsx', diffs: [{ path: 'web/app/connections/page.tsx', kind: 'update', diff: CONNECTIONS_DIFF }] }, at(1, 18, 44)),
                step('c5', 'command', { command: 'npm test -- connections', exit_code: 1, duration_ms: 9100, is_error: false, output: 'FAIL web/app/connections/page.test.tsx\n  ✕ shows each connection’s status (41 ms)\nTests: 1 failed, 23 passed\n' }, at(1, 18, 46)),
                step('c6', 'command', { command: 'npm test -- connections', exit_code: 0, duration_ms: 8400, output: 'PASS web/app/connections/page.test.tsx\nTests: 24 passed\n' }, at(1, 18, 50)),
            ],
        },
        { id: 'm3', role: 'user', text: 'Customers say webhook retries stop after the first failure since Friday. Can you find out why and fix it?', created_at: at(0, 10, 2), operation_id: 'op-t1', author: { type: 'account', id: null, name: 'Rowan Hale' } },
        {
            id: 'm4',
            role: 'assistant',
            text: 'Found the cause: the retry worker reads `max_attempts` from each connection, and Friday’s migration set it to 1 for every connection made in the dashboard.\n\n1. Fix the default and set it back to 5\n2. Add a test that a dashboard connection retries 5 times\n3. Re-send the 212 webhooks that gave up since Friday\n\nI’m on 1 and 2 now, and I’ll check with you before 3, since it sends to customers’ servers.',
            created_at: at(0, 10, 3),
            operation_id: 'op-t1',
            tool_calls: [
                step('d1', 'read', { path: 'app/retries/worker.py' }, at(0, 10, 2)),
                step('d2', 'command', { command: 'git log --since=friday --oneline -- migrations/', exit_code: 0, duration_ms: 400, output: '4c1e9a2 Backfill connection defaults\n91b0d17 Add connection.max_attempts\n' }, at(0, 10, 2)),
                step('d3', 'read', { path: 'migrations/0042_connection_defaults.py' }, at(0, 10, 3)),
            ],
        },
        { id: 'm5', role: 'user', text: 'Can you tag me on the pull request? I’d like to review the migration before it ships.', created_at: at(0, 10, 5), operation_id: 'op-t2', author: { type: 'user', id: 'u-priya', name: 'Priya Shah' } },
        { id: 'm6', role: 'assistant', text: 'Will do, Priya. I’ll add you as the reviewer when I open it.', created_at: at(0, 10, 5), operation_id: 'op-t2' },
        // Posts in #launch that mention it: the card draws them as the channel did, the text it read behind a fold.
        {
            id: 'm6a',
            role: 'user',
            text: 'You are @Wirefern in the channel "launch" (channel_id ch_launch) of the space "NoClick" (workspace_id ws_noclick). Other members: @Growth (agent), Priya Shah (person).\nNew messages since your last turn:\n\nGrowth: @Wirefern a customer asks whether the webhooks that failed since Friday will be sent again once the fix is out.\nowner: Good question. @Wirefern what’s the plan?\n\nReply with your message to the channel: your reply is posted for you, so never post it yourself too.',
            created_at: at(0, 10, 6),
            operation_id: 'op-c1',
            chat: 'channel:ch_launch',
            channel: {
                id: 'ch_launch',
                name: 'launch',
                space: { id: 'ws_noclick', name: 'NoClick' },
                thread: null,
                posts: [
                    { id: 'l9', author: { type: 'agent', id: 'a-growth', name: 'Growth' }, text: '@Wirefern a customer asks whether the webhooks that failed since Friday will be sent again once the fix is out.', created_at: at(0, 10, 5), thread_id: null, files: [] },
                    { id: 'l10', author: { type: 'account', id: null, name: 'owner' }, text: 'Good question. @Wirefern what’s the plan?', created_at: at(0, 10, 6), thread_id: null, files: [] },
                ],
            },
        },
        {
            id: 'm6b',
            role: 'assistant',
            text: 'Yes. Once the default is back to 5, I’ll re-send the 212 that gave up since Friday, after Rowan’s OK, since it sends to customers’ servers.',
            created_at: new Date(Date.parse(at(0, 10, 6)) + 14_000).toISOString(),
            operation_id: 'op-c1',
            tool_calls: [step('e1', 'command', { command: 'psql -c "select count(*) from deliveries where gave_up_at > \'friday\'"', exit_code: 0, duration_ms: 600, output: ' count \n-------\n   212\n' }, at(0, 10, 6))],
        },
        { id: 'm7', role: 'user', text: 'Go ahead with 1 and 2.', created_at: new Date(Date.now() - 4 * 60_000).toISOString(), operation_id: 'op-live', author: { type: 'account', id: null, name: 'Rowan Hale' } },
    ];
}

const MIGRATION_DIFF = `@@ -3,4 +3,4 @@ def upgrade(connection):
     if connection.made_in == "dashboard":
-        connection.max_attempts = 1
+        connection.max_attempts = connection.max_attempts or 5
     connection.save()
`;

/** The live turn under way: two edits made, the retry tests running. */
export function busyLive(op = 'op-live'): LiveEvent[] {
    return [
        { type: 'tool_call', id: 'e1', source: 'harness', kind: 'edit', tool: 'edit', path: 'migrations/0042_connection_defaults.py', operation_id: op },
        { type: 'diff', id: 'e1', path: 'migrations/0042_connection_defaults.py', kind: 'update', diff: MIGRATION_DIFF, operation_id: op },
        { type: 'tool_result', id: 'e1', source: 'harness', kind: 'edit', tool: 'edit', is_error: false, duration_ms: 1200, operation_id: op },
        { type: 'tool_call', id: 'e2', source: 'harness', kind: 'edit', tool: 'edit', path: 'tests/test_dashboard_retries.py', operation_id: op },
        { type: 'diff', id: 'e2', path: 'tests/test_dashboard_retries.py', kind: 'add', diff: 'def test_dashboard_connection_retries_five_times(dashboard_connection):\n    assert deliver_until_given_up(dashboard_connection) == 5\n', operation_id: op },
        { type: 'tool_result', id: 'e2', source: 'harness', kind: 'edit', tool: 'edit', is_error: false, duration_ms: 900, operation_id: op },
        { type: 'tool_call', id: 'e3', source: 'harness', kind: 'command', tool: 'shell', command: 'pytest tests/ -k retries -q', operation_id: op },
        { type: 'output', id: 'e3', text: 'tests/test_retry_worker.py::test_first_attempt_waits_one_second PASSED\ntests/test_retry_worker.py::test_retry_after_header_wins PASSED\n', operation_id: op },
    ];
}

/** An approval its harness waits on: pushing the branch. */
export function pushAsk(op = 'op-live'): Json {
    return {
        id: 'req-push',
        kind: 'approval',
        status: 'pending',
        action: 'command',
        title: 'Run git push origin fix/dashboard-retries',
        detail: 'git push origin fix/dashboard-retries',
        options: [
            { option_id: 'allow_once', name: 'Approve', kind: 'allow_once' },
            { option_id: 'allow_always', name: 'Always allow', kind: 'allow_always' },
            { option_id: 'reject_once', name: 'Decline', kind: 'reject_once' },
        ],
        operation_id: op,
        created_at: new Date(Date.now() - 30_000).toISOString(),
    };
}

/** A question its harness asks: which webhooks to resend. */
export function resendQuestion(op = 'op-live'): Json {
    return {
        id: 'req-resend',
        kind: 'question',
        status: 'pending',
        questions: [
            {
                id: 'Which webhooks should I resend?',
                header: 'Resend',
                question: 'Which webhooks should I resend?',
                multi_select: false,
                options: [
                    { label: 'The 212 that gave up since Friday', description: 'Every dashboard connection' },
                    { label: 'Only paying customers’ ones', description: '38 of them' },
                ],
            },
        ],
        options: [{ option_id: 'reject_once', name: 'Decline', kind: 'reject_once' }],
        operation_id: op,
        created_at: new Date(Date.now() - 20_000).toISOString(),
    };
}

/** The live turn's operation, running. */
export function liveOperation(op = 'op-live'): Json {
    return { object: 'operation', id: op, kind: 'agent.message', status: 'running', conversation: 'main', created_at: new Date(Date.now() - 4 * 60_000).toISOString(), started_at: new Date(Date.now() - 4 * 60_000).toISOString(), updated_at: new Date().toISOString() };
}

const LONG_URL = 'https://dashboard.wirefern.test/settings/connections/conn_5c1e0b8a6f0e4b8c9a710c2d4e8f1a01/webhooks/deliveries?status=failed&since=2026-11-07T00:00:00Z&page_token=next-page-400';
const LONG_JSON = JSON.stringify({ id: 'conn_5c1e0b8a6f0e4b8c9a710c2d4e8f1a01', status: 'failed', attempts: 1, max_attempts: 1, last_error: 'connect ETIMEDOUT 52.14.199.83:443', headers: { 'x-wirefern-signature': 'sha256=9f8e7d6c5b4a39281706f5e4d3c2b1a09f8e7d6c5b4a39281706f5e4d3c2b1a0' } });
const LONG_BASE64 = 'eyJzdWIiOiJjb25uXzVjMWUwYjhhNmYwZTRiOGM5YTcxMGMyZDRlOGYxYTAxIiwiZXhwIjoxNzk1MDAwMDAwLCJzY29wZSI6IndlYmhvb2tzOnJlYWQgd2ViaG9va3M6d3JpdGUifQ'.repeat(3);
const LONG_COMMAND = `curl -sS -X POST "${LONG_URL}" -H "Authorization: Bearer ${LONG_BASE64.slice(0, 120)}" --data '${LONG_JSON}'`;
const LONG_PATH = 'web/app/settings/connections/[connectionId]/webhooks/deliveries/components/DeliveryRetryScheduleTimelineWithBackoffExplanation.tsx';
const WIDE_TABLE = `| connection | delivery | status | attempts | last error | next retry | url |\n| --- | --- | --- | --- | --- | --- | --- |\n| conn_5c1e0b8a6f0e4b8c9a710c2d4e8f1a01 | dlv_0b8a6f0e4b8c9a710c2d4e8f1a015c1e | failed | 1 | connect ETIMEDOUT 52.14.199.83:443 | never | ${LONG_URL} |`;
const WIDE_CODE = '```json\n' + LONG_JSON + '\n```';

/** What an agent writes for itself, as long as it likes: a wake-up's reason, a job's brief, with a token in it. */
const LONG_NOTE = `Check the retry job once the build lands. Constraints: preserve the 30-second schedule and the production webhook behavior; do not add retries or duplicate outbound calls. If it produces a safe fix, verify a scheduled run succeeds before saying fixed; tell the owner only if it keeps failing (${LONG_URL})`;

/** Long unbroken text in every kind of row: a URL, one-line JSON and base64, a wide table and code block, a long
 *  command and its output, a long file path, a long word in your bubble, and what an agent writes for itself (a
 *  wake-up's reason, a schedule's name, a note, what it asked, an approval and a question). Nothing of it may widen
 *  the thread. */
export function overflowHistory(): Json[] {
    const t = at(0, 9, 0);
    return [
        { id: 'o-wake', role: 'user', text: LONG_NOTE, created_at: at(0, 8, 0), operation_id: 'op-o0', trigger: { kind: 'wakeup', id: 'wk-1', title: LONG_NOTE } },
        { id: 'o-wake-reply', role: 'assistant', text: 'The build is still running; I’ll look again when it lands.', created_at: at(0, 8, 0), operation_id: 'op-o0' },
        { id: 'o-cron', role: 'user', text: 'Every morning', created_at: at(0, 8, 30), operation_id: 'op-o00', trigger: { kind: 'cron', id: 'tr-1', title: `Every weekday at 9: ${LONG_NOTE}` } },
        { id: 'o-note', role: 'note', text: `A note for itself: ${LONG_NOTE} ${LONG_BASE64}`, created_at: at(0, 8, 31) },
        { id: 'o0', role: 'user', text: `/review ${LONG_BASE64}`, command: { name: 'review', arguments: LONG_BASE64 }, created_at: t, operation_id: 'op-o1', author: { type: 'account', id: null, name: 'Rowan Hale' } },
        { id: 'o1', role: 'user', text: `Look at ${LONG_URL} and tell me why supercalifragilisticexpialidocious${'x'.repeat(80)} keeps failing`, created_at: t, operation_id: 'op-o1', author: { type: 'account', id: null, name: 'Rowan Hale' } },
        {
            id: 'o2',
            role: 'assistant',
            text: `Here's what the API said: ${LONG_JSON}\n\nIts token: ${LONG_BASE64}, or in code \`${LONG_BASE64}\`\n\n${WIDE_TABLE}\n\n${WIDE_CODE}\n\nThe page: ${LONG_URL}`,
            created_at: t,
            operation_id: 'op-o1',
            tool_calls: [
                step('o2a', 'command', { command: LONG_COMMAND, exit_code: 0, duration_ms: 900, output: `${LONG_JSON}\n${LONG_BASE64}\n` }, t),
                step('o2b', 'edit', { path: LONG_PATH, diffs: [{ path: LONG_PATH, kind: 'update', diff: `@@ -1,1 +1,1 @@\n-${LONG_JSON}\n+${LONG_JSON.replace('failed', 'retrying')}\n` }] }, t),
                { id: 'o2c', source: null, kind: 'tool', tool: 'noclick__api_call', created_at: t, arguments: { operation: 'webhooks_deliveries_list', url: LONG_URL }, result: JSON.parse(LONG_JSON) },
                { id: 'request:o2d', source: 'harness', kind: 'tool', tool: 'request', created_at: t, arguments: { title: `Resend ${LONG_URL}`, action: 'command' }, result: `allow_once: ${LONG_BASE64}` },
            ],
        },
    ];
}

/** What its harness asks in that turn, waiting on you, as long as it likes: an approval with its reason, and a question
 *  whose option is a whole note. */
export function overflowAsks(): Json[] {
    const t = at(0, 9, 0);
    return [
        { id: 'req-o-approve', kind: 'approval', status: 'pending', action: 'command', title: `Run ${LONG_COMMAND}`, detail: LONG_COMMAND, reason: LONG_NOTE, options: [{ option_id: 'allow_once', name: 'Approve', kind: 'allow_once' }, { option_id: 'reject_once', name: 'Decline', kind: 'reject_once' }], operation_id: 'op-o1', created_at: t },
        { id: 'req-o-ask', kind: 'question', status: 'pending', questions: [{ id: 'q1', header: 'Which', question: `Which of these should I resend: ${LONG_URL}?`, multi_select: false, options: [{ label: LONG_NOTE, description: LONG_URL }] }], options: [{ option_id: 'reject_once', name: 'Decline', kind: 'reject_once' }], operation_id: 'op-o1', created_at: t },
    ];
}
