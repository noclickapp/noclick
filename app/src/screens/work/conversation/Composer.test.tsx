// @vitest-environment happy-dom
// The one box of every agent conversation (Work's, and the Chat page's): / and $ open only where there is something to
// offer (NoClick's commands a page runs, the skills a harness reports), and its line says only what it offers; its "+"
// takes the paperclip's place, and what a message points at goes with the words; words a page held for it before it was
// drawn are in it as it opens; /loop runs as NoClick's own command, never sent as a message.
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { AgentCommands } from 'noclick';
import { TooltipProvider } from '@/ui/tooltip';

import { fill } from '@/slots';
import { COMPOSER_SOURCES } from '../slots';
import { Composer, type ComposerProps } from './Composer';

// The "+" lists no automations and no accounts.
fill(COMPOSER_SOURCES, { useAutomations: () => ({ automations: [], loading: false }), useAccounts: () => ({ accounts: [], loaded: true }), when: (iso) => iso });
import { CONTROL_NAMES } from './menus';

afterEach(cleanup);

const SKILLED = { commands: [], skills: [{ name: 'deploy', description: 'Ship the site' }], mapped: [], withheld: [], notSupported: {}, asOf: null, readFrom: null, capabilities: {}, harness: 'claude_code', raw: {} } as unknown as AgentCommands;

function box(over: Partial<ComposerProps> = {}) {
    const props: ComposerProps = {
        agentName: 'Scout',
        harnessLabel: 'Claude Code',
        working: false,
        ready: true,
        commands: null,
        queued: [],
        requests: [],
        subagents: [],
        onShowSubagents: () => undefined,
        model: null,
        onControl: vi.fn(),
        drawer: null,
        onSend: vi.fn(async () => true),
        onStop: () => undefined,
        onUnqueue: async () => null,
        onAnswer: () => undefined,
        upload: vi.fn(),
        ...over,
    };
    render(
        <TooltipProvider>
            <Composer {...props} />
        </TooltipProvider>
    );
    return { props, text: screen.getByRole('textbox') as HTMLTextAreaElement };
}

describe('the one box', () => {
    it('opens / and $ only where there is something to offer, and its line says only that', async () => {
        const { text } = box({ controls: [] });
        expect(text.placeholder).toBe('Ask Scout anything');
        fireEvent.change(text, { target: { value: '/' } });
        expect(screen.queryByRole('listbox')).toBeNull();
        fireEvent.change(text, { target: { value: 'pay $5' } });
        expect(screen.queryByRole('listbox')).toBeNull();
        cleanup();

        const skilled = box({ commands: SKILLED, mentionables: async () => [] }).text;
        expect(skilled.placeholder).toBe('Ask Scout anything. @ files, $ skills, / commands');
        fireEvent.change(skilled, { target: { value: '$' } });
        expect((await screen.findByRole('listbox', { name: 'Skills' })).textContent).toContain('$deploy');
        fireEvent.change(skilled, { target: { value: '/' } });
        const commands = await screen.findByRole('listbox', { name: 'Commands' });
        expect(commands.textContent).toContain('/loop');
        expect(commands.textContent).toContain('/usage');
    });

    it('has its "+" in the paperclip’s place, and sends what a message points at with the words', async () => {
        const { props, text } = box({ putBack: { text: 'Why did this fail?', n: 1, references: [{ kind: 'automation', id: 'wf-1', label: 'Morning brief' }] } });
        expect(screen.getByRole('button', { name: 'Add files, automations or accounts' })).toBeTruthy();
        expect(screen.queryByRole('button', { name: 'Attach files' })).toBeNull();
        // Words a page held for it before it was drawn, with what they point at.
        expect(text.value).toBe('Why did this fail?');
        expect(document.querySelector('[data-chip=reference]')!.textContent).toContain('Morning brief');
        fireEvent.keyDown(text, { key: 'Enter' });
        await waitFor(() => expect(props.onSend).toHaveBeenCalledTimes(1));
        expect(props.onSend).toHaveBeenCalledWith(expect.objectContaining({ text: 'Why did this fail?', references: [{ kind: 'automation', id: 'wf-1', label: 'Morning brief' }] }));
        expect(document.querySelector('[data-chip]')).toBeNull();
    });

    it('runs /rename as NoClick’s own command, never sent to the model, and offers it only where the agent can be renamed', async () => {
        const { props, text } = box();
        fireEvent.change(text, { target: { value: '/ren' } });
        const commands = await screen.findByRole('listbox', { name: 'Commands' });
        expect(commands.textContent).toContain('/rename');
        expect(commands.textContent).toContain('<new name>');
        // Picked from the menu, it waits for the name.
        fireEvent.keyDown(text, { key: 'Enter' });
        expect(text.value).toBe('/rename ');
        fireEvent.change(text, { target: { value: '/rename Bakery helper' } });
        fireEvent.keyDown(text, { key: 'Enter' });
        expect(props.onControl).toHaveBeenLastCalledWith('rename', 'Bakery helper');
        // Alone, it opens the rename in place.
        fireEvent.change(text, { target: { value: '/rename' } });
        fireEvent.keyDown(text, { key: 'Escape' });
        fireEvent.keyDown(text, { key: 'Enter' });
        expect(props.onControl).toHaveBeenLastCalledWith('rename', '');
        expect(props.onSend).not.toHaveBeenCalled();
        cleanup();

        // A NoClick's box (every command but /rename) never offers it.
        box({ controls: CONTROL_NAMES.filter((c) => c !== 'rename') });
        fireEvent.change(screen.getByRole('textbox'), { target: { value: '/ren' } });
        expect(screen.queryByRole('listbox', { name: 'Commands' })?.textContent ?? '').not.toContain('/rename');
    });

    it('runs /loop as NoClick’s own command with what follows it, never as a message', () => {
        const { props, text } = box({ controls: ['loop'] });
        expect(text.placeholder).toBe('Ask Scout anything. / commands');
        fireEvent.change(text, { target: { value: '/loop 5m check the deploy' } });
        fireEvent.keyDown(text, { key: 'Enter' });
        expect(props.onControl).toHaveBeenCalledWith('loop', '5m check the deploy');
        expect(props.onSend).not.toHaveBeenCalled();
        expect(text.value).toBe('');
    });
});
