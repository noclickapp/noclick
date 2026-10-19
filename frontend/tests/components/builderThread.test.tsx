// @vitest-environment jsdom
// The builder thread follows its newest change: the one box the scroller watches holds every change (a style it draws
// first can't stand in for it), and a request of the reader's own pins it to the bottom even when it lands together
// with its reply, as a send registers both at once. A reply says how its run ended: stopped without finishing, or
// hit by an error, with a Try again that sends its change's request again; an action its run never finished says so.
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { BuilderThread, requestsIn } from '~/components/chat/builder/BuilderThread';
import type { Message } from '~/components/chat/types';
import { mapPersistedMessage } from '~/hooks/conversationRestoreMapping';

// The panel's field titles read the node schemas; none are needed here.
vi.mock('~/utils/nodeSchemas', () => ({ getNodeSchema: () => undefined }));

beforeEach(() => {
    vi.stubGlobal(
        'ResizeObserver',
        class {
            observe() {}
            unobserve() {}
            disconnect() {}
        },
    );
});

afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
});

const ask = (text: string): Message => ({ text, isUser: true, isComplete: true });
const answer = (text: string): Message => ({ text: '', isUser: false, isComplete: true, editSegments: [{ type: 'text', text }] });

describe('the builder thread', () => {
    it('keeps every change inside the one box its scroller follows', () => {
        render(<BuilderThread messages={[ask('Add Gmail'), answer('Added it.'), ask('Make it shorter'), answer('Done.')]} />);
        const followed = screen.getByTestId('builder-thread').firstElementChild;
        const changes = screen.getAllByTestId('builder-change');
        expect(changes).toHaveLength(2);
        for (const change of changes) expect(followed?.contains(change)).toBe(true);
    });

    it('counts a send that lands with its reply as a new request', () => {
        const before = [ask('Add Gmail'), answer('Added it.')];
        const sent = [...before, ask('Make it shorter'), { text: '', isUser: false, isComplete: false } as Message];
        expect(requestsIn(sent)).toBeGreaterThan(requestsIn(before));
    });
});

describe('how a reply’s run ended', () => {
    const retries = () => {
        const sent: unknown[] = [];
        const listen = (event: Event) => sent.push((event as CustomEvent).detail);
        document.addEventListener('noclick:builder:retry', listen);
        return { sent, stop: () => document.removeEventListener('noclick:builder:retry', listen) };
    };

    it('says a run that stopped without finishing did, as reloaded, and Try again sends its request again', () => {
        const stopped = mapPersistedMessage({ role: 'assistant', message: '', edit_segments: [{ type: 'text', text: 'Adding it.' }], incomplete: true });
        render(<BuilderThread messages={[ask('Add Gmail'), stopped]} conversationId="conv-1" />);
        expect(screen.getByTestId('builder-incomplete').textContent).toContain('Stopped without finishing');
        expect(screen.queryByTestId('builder-failed')).toBeNull();
        const heard = retries();
        fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
        heard.stop();
        expect(heard.sent).toEqual([{ prompt: 'Add Gmail', conversationId: 'conv-1' }]);
    });

    it('says a run that hit an error did', () => {
        const failed: Message = { text: '', isUser: false, isComplete: true, failed: true, error: 'Provider timed out', editSegments: [] };
        render(<BuilderThread messages={[ask('Add Gmail'), failed]} conversationId="conv-1" />);
        expect(screen.getByTestId('builder-failed').textContent).toContain('It hit an error and stopped');
        expect(screen.queryByTestId('builder-incomplete')).toBeNull();
    });

    it('offers Try again only where there is a request it can send again', () => {
        const stopped: Message = { text: '', isUser: false, isComplete: true, incomplete: true };
        const drawn: Message = {
            text: 'Like this', isUser: true, isComplete: true,
            content: [{ type: 'text', text: 'Like this' }, { type: 'image_url', image_url: { url: 'data:image/png;base64,AA' } }],
        };
        render(<BuilderThread messages={[stopped, drawn, { ...stopped }]} conversationId="conv-1" />);
        expect(screen.getAllByTestId('builder-incomplete')).toHaveLength(2);
        expect(screen.queryByRole('button', { name: 'Try again' })).toBeNull();
    });

    it('never sends an import again as the sentence it went with, as reloaded', () => {
        const imported = mapPersistedMessage({ role: 'user', message: 'Import this n8n workflow into NoClick.', n8n_import: { node_count: 3 } });
        const stopped = mapPersistedMessage({ role: 'assistant', message: '', edit_segments: [], incomplete: true });
        render(<BuilderThread messages={[imported, stopped]} conversationId="conv-1" />);
        expect(imported.n8nImportNodeCount).toBe(3);
        expect(screen.getByTestId('builder-incomplete')).toBeTruthy();
        expect(screen.queryByRole('button', { name: 'Try again' })).toBeNull();
    });

    it('holds Try again while a run is going or a question waits on an answer, which a send would answer', () => {
        const stopped: Message = { text: '', isUser: false, isComplete: true, incomplete: true };
        const asking: Message = { text: '', isUser: false, isComplete: true, pendingAsk: { ask_id: 'a1', inputs: [{ nodeId: 'gm' }] } };
        const running: Message = { text: '', isUser: false, isComplete: false };
        for (const last of [asking, running]) {
            render(<BuilderThread messages={[ask('Add Gmail'), stopped, ask('Add Slack'), last]} conversationId="conv-1" />);
            expect(screen.getByTestId('builder-incomplete')).toBeTruthy();
            expect(screen.queryByRole('button', { name: 'Try again' })).toBeNull();
            cleanup();
        }
    });

    it('says an action its run never finished didn’t, and the actions as a whole didn’t go cleanly', () => {
        const step = (state: string) => ({ type: 'builder_step', status: 'completed', run: 'r1', batch: 1, index: 0, op: 'add_node', target: 'Google Calendar', state });
        const cut: Message = {
            text: '', isUser: false, isComplete: true, wasInterrupted: true,
            editSegments: [{ type: 'text', text: 'Adding it.' }, { type: 'events', events: [step('running')] as never }],
        };
        render(<BuilderThread messages={[ask('Add my calendar'), cut]} />);
        fireEvent.click(screen.getByRole('button', { name: /1 action/ }));
        expect(screen.getByTestId('builder-action-unfinished').textContent).toBe('Adding step · Google Calendardidn’t finish');
        expect(screen.getByTestId('builder-actions-failed')).toBeTruthy();
    });
});
