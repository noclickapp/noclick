// Anchors the terminal-detection contract the relay-independent reconciler in
// useAgentChat depends on (fix/agent-turn-failure-surfacing): a persisted
// agent error / completed response must map to a bubble that satisfies the
// reconciler's isTerminal predicate, while an in-flight or user entry must not.
// Runs the real persistedEventsToChatMessages in the browser.

import { nc } from '~/lib/nc';
import { persistedEventsToChatMessages } from '~/hooks/useAgentChat';

// Mirror of the reconciler's isTerminal check — kept in sync deliberately.
function isTerminal(m: { isUser: boolean; isComplete: boolean; text?: string; error?: string }): boolean {
    return (
        !m.isUser &&
        m.isComplete &&
        ((m.text?.trim().length ?? 0) > 0 || !!m.error)
    );
}

export default async function () {
    // A persisted turn-error (the shape claude_code's runner.persist_agent_error
    // writes, and the cancelled-assistant shape).
    const errored = persistedEventsToChatMessages([
        { role: 'user', message: 'hi' },
        { role: 'assistant', message: 'Your Anthropic account has no API credits…', cancelled: true },
    ] as never);
    const lastErr = errored[errored.length - 1];
    nc.assert.truthy(lastErr && !!lastErr.error, 'persisted error must produce an error bubble');
    nc.assert.truthy(isTerminal(lastErr), 'error bubble must satisfy isTerminal');

    // A completed text response is terminal.
    const ok = persistedEventsToChatMessages([
        { role: 'user', message: 'hi' },
        { role: 'assistant', message: 'All done — synced 42 rows.' },
    ] as never);
    nc.assert.truthy(isTerminal(ok[ok.length - 1]), 'completed response must satisfy isTerminal');

    // A lone user message is NOT terminal — the turn is still in flight.
    const pending = persistedEventsToChatMessages([{ role: 'user', message: 'hi' }] as never);
    nc.assert.truthy(
        pending.every(m => !isTerminal(m)),
        'a pending (user-only) transcript must not read as terminal',
    );

    return {
        erroredTerminal: isTerminal(lastErr),
        errorText: lastErr.error?.slice(0, 60),
    };
}
