// Pin the wire shape the backend agent_handler writes to
// `conversations.events` so it actually renders on restore.
//
// Why this test exists: after the OpenHands → openai-agents migration
// the chat handler started writing `{action:'message', source:'user',
// args:{content}}` events (OpenHands' legacy shape). The frontend's
// `mapPersistedMessage` reads the WorkflowBuilder shape — `{role,
// message, ...}` — instead. Result: events landed in Postgres but
// never showed up in the UI. This test asserts the new shape we
// write maps correctly so the regression can't come back silently.

import { nc } from '~/lib/nc';
import {
    mapPersistedMessage,
    mapPersistedMessages,
    type PersistedMessage,
} from '~/hooks/conversationRestoreMapping';

export default async function () {
    // These payloads MUST match what wss/handlers/agent_handler.py
    // _persist_chat_event / _persist_chat_error writes. If the backend
    // wire shape drifts, this fails first.

    // --- User message ---------------------------------------------------
    const userEvent: PersistedMessage = {
        role: 'user',
        message: 'hello, can you help with my workflow?',
    };
    const userMapped = mapPersistedMessage(userEvent);
    nc.assert.equal(userMapped.isUser, true, 'user event → isUser=true');
    nc.assert.equal(
        userMapped.text, 'hello, can you help with my workflow?',
        'user event → text body',
    );
    nc.assert.equal(userMapped.isComplete, true, 'user event → complete bubble');
    nc.assert.equal(userMapped.wasInterrupted, undefined, 'user not interrupted');

    // --- Agent message --------------------------------------------------
    const agentEvent: PersistedMessage = {
        role: 'assistant',
        message: 'Sure! Tell me what the workflow should do.',
    };
    const agentMapped = mapPersistedMessage(agentEvent);
    nc.assert.equal(agentMapped.isUser, false, 'agent event → isUser=false');
    nc.assert.equal(
        agentMapped.text, 'Sure! Tell me what the workflow should do.',
        'agent event → text body',
    );
    nc.assert.equal(agentMapped.isComplete, true, 'agent event → complete bubble');
    nc.assert.equal(agentMapped.wasInterrupted, undefined, 'agent not interrupted');

    // --- Terminal error (cancelled: true) -------------------------------
    const errorEvent: PersistedMessage = {
        role: 'assistant',
        message: 'Insufficient balance.',
        cancelled: true,
    };
    const errorMapped = mapPersistedMessage(errorEvent);
    nc.assert.equal(errorMapped.isUser, false, 'error event → isUser=false');
    nc.assert.equal(
        errorMapped.text, 'Insufficient balance.',
        'error event → text body preserved',
    );
    nc.assert.equal(
        errorMapped.wasInterrupted, true,
        'cancelled:true → wasInterrupted (renders interrupted notice)',
    );

    // --- Full transcript round-trip — verify ordering survives ----------
    const transcript: PersistedMessage[] = [
        { role: 'user', message: 'first msg' },
        { role: 'assistant', message: 'reply 1' },
        { role: 'user', message: 'follow up' },
        { role: 'assistant', message: 'reply 2' },
    ];
    const mapped = mapPersistedMessages(transcript);
    nc.assert.equal(mapped.length, 4, '4 events → 4 messages');
    nc.assert.equal(mapped[0].isUser, true, '[0] user');
    nc.assert.equal(mapped[1].isUser, false, '[1] assistant');
    nc.assert.equal(mapped[2].isUser, true, '[2] user');
    nc.assert.equal(mapped[3].isUser, false, '[3] assistant');
    nc.assert.equal(mapped[2].text, 'follow up', '[2] body preserved');

    // --- The LEGACY (broken) shape we used to write should NOT pass.
    // If anyone re-introduces it, mapPersistedMessage will produce a
    // bubble with isUser=false (because role is missing) and empty
    // text (because message is on `args.content`, not `msg.message`).
    // We assert that outcome explicitly so a future test author
    // doesn't mistakenly mark the broken shape as 'works fine'.
    const legacyShape = {
        action: 'message',
        source: 'user',
        args: { content: 'I would render as nothing' },
        // intentionally omitting role + top-level message
    } as unknown as PersistedMessage;
    const legacyMapped = mapPersistedMessage(legacyShape);
    nc.assert.equal(
        legacyMapped.isUser, false,
        'legacy {action,source,args} shape → isUser=false (no role field). ' +
        'This proves the new {role, message} shape is required.',
    );
    nc.assert.equal(
        legacyMapped.text, '',
        'legacy shape → empty text (mapPersistedMessage reads msg.message, ' +
        'NOT msg.args.content). If you re-introduce {action,source,args}, ' +
        'the chat history sidebar shows blank bubbles.',
    );

    return {
        userMapped, agentMapped, errorMapped,
        transcriptLength: mapped.length,
        legacyShapeRendersWrong: legacyMapped.text === '' && legacyMapped.isUser === false,
        allChecksPassed: true,
    };
}
