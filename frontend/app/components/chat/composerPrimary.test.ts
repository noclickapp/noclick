// The one rule for a chat box's round button, as each box asks it: the Chat page (stop and steer, no queue), Work
// (stop, steer and queue), and the socket chats (an interface block, a shared agent's page), which wait for a turn to
// end.
import { describe, expect, it } from 'vitest';
import { composerPrimary, type ComposerState } from './composerPrimary';

const chat = (s: Partial<ComposerState>) => composerPrimary({ filled: false, ready: true, canStop: true, canSteer: true, ...s });
const work = (s: Partial<ComposerState>) => composerPrimary({ filled: false, ready: true, canStop: true, canSteer: true, canQueue: true, ...s });
const socket = (s: Partial<ComposerState>) => composerPrimary({ filled: false, ready: true, ...s });

describe('composerPrimary', () => {
    it('sends what’s written, and nothing until something is', () => {
        expect(chat({})).toEqual({ kind: 'send', disabled: true });
        expect(chat({ filled: true })).toEqual({ kind: 'send', disabled: false });
        expect(chat({ filled: true, ready: false })).toEqual({ kind: 'send', disabled: true });
        expect(chat({ filled: true, uploading: true })).toEqual({ kind: 'send', disabled: true });
        expect(chat({ filled: true, failed: true })).toEqual({ kind: 'send', disabled: true });
        expect(work({ filled: true, sending: true })).toEqual({ kind: 'send', disabled: true });
    });

    it('while the agent works, stops it from an empty box and joins it with words', () => {
        expect(chat({ working: true })).toEqual({ kind: 'stop', disabled: false });
        expect(chat({ working: true, ready: false })).toEqual({ kind: 'stop', disabled: true });
        expect(chat({ working: true, filled: true })).toEqual({ kind: 'steer', disabled: false });
        expect(work({ working: true, filled: true })).toEqual({ kind: 'steer', disabled: false });
    });

    it('queues behind the turn where the box can: a held ⌘, a harness command, or files, which can’t join it', () => {
        expect(work({ working: true, filled: true, queueHeld: true })).toEqual({ kind: 'queue', disabled: false });
        expect(work({ working: true, filled: true, command: 'harness' })).toEqual({ kind: 'queue', disabled: false });
        expect(work({ working: true, filled: true, unsteerable: true })).toEqual({ kind: 'queue', disabled: false });
        // The Chat page has no queue: files wait for the turn to end.
        expect(chat({ working: true, filled: true, unsteerable: true })).toEqual({ kind: 'steer', disabled: true });
    });

    it('runs one of NoClick’s own commands at once, and declines an approval with the words typed', () => {
        expect(work({ working: true, filled: true, command: 'control' })).toEqual({ kind: 'send', disabled: false });
        expect(work({ working: true, filled: true, approval: true })).toEqual({ kind: 'send', disabled: false });
    });

    it('answers a question its harness asked', () => {
        expect(work({ question: true, working: true })).toEqual({ kind: 'submit', disabled: true });
        expect(work({ question: true, working: true, filled: true })).toEqual({ kind: 'submit', disabled: false });
    });

    it('writes to a subagent: words join its turn, never stop or queue it', () => {
        expect(work({ scoped: true, working: true })).toEqual({ kind: 'send', disabled: true });
        expect(work({ scoped: true, working: true, filled: true, queueHeld: true })).toEqual({ kind: 'steer', disabled: false });
        expect(work({ scoped: true, filled: true })).toEqual({ kind: 'send', disabled: false });
    });

    it('waits for the turn to end in a box that can neither stop nor join it', () => {
        expect(socket({ working: true })).toEqual({ kind: 'send', disabled: true });
        expect(socket({ working: true, filled: true })).toEqual({ kind: 'send', disabled: true });
        expect(socket({ filled: true })).toEqual({ kind: 'send', disabled: false });
    });
});
