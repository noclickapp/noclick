// Anchors the terminal-detection contract the relay-independent reconciler in
// useAgentChat depends on (fix/agent-turn-failure-surfacing): a persisted
// agent error / completed response must map to a bubble that satisfies the
// reconciler's isTerminal predicate, while an in-flight or user entry must not.
// Runs the real persistedEventsToChatMessages in the browser.

import { nc } from '~/lib/nc';
import { persistedEventsToChatMessages, dedupeConsecutiveErrors } from '~/hooks/useAgentChat';

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

    // Duplicate-error collapse: the live agent:state error (appended) and the
    // persisted action:error (resume-prepended) are the same failure; a relay
    // redelivery during the resume window can land both. Dedup must collapse
    // them regardless of order, but keep genuinely different errors + the user
    // turn between them.
    const err = 'Your Anthropic account has no API credits…';
    const dupAdjacent = dedupeConsecutiveErrors([
        { isUser: true, text: 'hi', isComplete: true },
        { isUser: false, text: '', isComplete: true, error: err },
        { isUser: false, text: '', isComplete: true, error: err },
    ]);
    nc.assert.equal(dupAdjacent.length, 2, 'adjacent identical errors collapse to one');

    const distinct = dedupeConsecutiveErrors([
        { isUser: false, text: '', isComplete: true, error: err },
        { isUser: false, text: '', isComplete: true, error: 'a different failure' },
    ]);
    nc.assert.equal(distinct.length, 2, 'different errors are preserved');

    return {
        erroredTerminal: isTerminal(lastErr),
        errorText: lastErr.error?.slice(0, 60),
        dedupCollapsed: dupAdjacent.length === 2,
    };
}
