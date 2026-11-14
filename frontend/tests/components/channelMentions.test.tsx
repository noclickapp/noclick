// @vitest-environment jsdom
// A message's @mentions: each that names one member of the channel is drawn as one, resolved as the platform resolves
// them (by name, ignoring case; a renamed agent by the names it went by too, drawn as its name now); anything else stays
// plain. The box's @ finds a renamed agent by its old name and puts in its new one.
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { useRef, useState } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ChannelComposer } from '~/components/shell/channels/ChannelComposer';
import { MessageBody } from '~/components/shell/channels/MessageBody';
import { YOU } from '~/components/shell/channels/model';
import type { ChannelMember } from '~/components/shell/channels/types';
import { TooltipProvider } from '~/components/ui/tooltip';

afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
});

const GROWTH: ChannelMember = { id: 'm_growth', kind: 'agent', name: 'Growth', hue: 'emerald' };
const PRIYA: ChannelMember = { id: 'm_priya', kind: 'human', name: 'Priya Shah' };
const NO_CHANNELS = new Map<string, string>();

function mentionsOf(text: string, members: ChannelMember[] = [YOU, GROWTH, PRIYA]) {
    const { container } = render(<MessageBody text={text} members={members} channels={NO_CHANNELS} onChannel={() => undefined} />);
    return [...container.querySelectorAll<HTMLElement>('[data-mention]')].map((el) => ({ text: el.textContent, kind: el.dataset.mention, className: el.className }));
}

describe('a message’s mentions', () => {
    it('draws an agent’s in its colour on its tint, a person’s in the accent, and yours', () => {
        const found = mentionsOf('@Growth, can you and @Priya Shah check it? cc @You');
        expect(found.map(({ text, kind }) => [text, kind])).toEqual([
            ['@Growth', 'agent'],
            ['@Priya Shah', 'human'],
            ['@You', 'you'],
        ]);
        expect(found[0].className).toContain('text-emerald-700');
        expect(found[0].className).toContain('bg-emerald-500/[0.14]');
        expect(found[1].className).toContain('bg-accent');
    });

    it('resolves a name in any case, as the platform does', () => {
        expect(mentionsOf('thanks @growth').map((m) => m.text)).toEqual(['@growth']);
    });

    it('leaves plain what names no one, or several', () => {
        expect(mentionsOf('@Growthy and mail@Growth and @Nobody')).toEqual([]);
        // Two members by one name: a mention names neither.
        const twins: ChannelMember[] = [YOU, { id: 'a1', kind: 'agent', name: 'Agent', hue: 'sky' }, { id: 'a2', kind: 'agent', name: 'agent', hue: 'violet' }];
        expect(mentionsOf('@Agent, look at this', twins)).toEqual([]);
        // One of them alone is named, whichever case it's written in.
        expect(mentionsOf('@AGENT, look', twins.slice(0, 2)).map((m) => m.text)).toEqual(['@AGENT']);
    });

    it('keeps a mention inside code as code', () => {
        expect(mentionsOf('run `@Growth deploy` later')).toEqual([]);
    });
});

const BAKERY: ChannelMember = { id: 'm_bakery', kind: 'agent', name: 'Bakery helper', hue: 'sky', formerNames: ['WhatsApp'] };

describe('a renamed agent', () => {
    it('is named by its old name in a message, drawn as its name now', () => {
        expect(mentionsOf('@WhatsApp, is the oven on? and @whatsapp again', [YOU, BAKERY]).map(({ text, kind }) => [text, kind])).toEqual([
            ['@Bakery helper', 'agent'],
            ['@Bakery helper', 'agent'],
        ]);
        expect(mentionsOf('@Bakery helper, thanks', [YOU, BAKERY]).map((m) => m.text)).toEqual(['@Bakery helper']);
        // A member that goes by the name now is the one it names.
        expect(mentionsOf('@WhatsApp hi', [YOU, BAKERY, { id: 'm_wa', kind: 'human', name: 'WhatsApp' }]).map(({ text, kind }) => [text, kind])).toEqual([['@WhatsApp', 'human']]);
    });

    it('is offered by its old name in the box’s @, and goes in by its new one', () => {
        function Box() {
            const [value, setValue] = useState('');
            const ref = useRef<HTMLTextAreaElement>(null);
            return (
                <ChannelComposer
                    channelName="orders"
                    value={value}
                    onChange={setValue}
                    attachments={[]}
                    onAddFiles={() => undefined}
                    onAddClip={() => undefined}
                    onRemoveAttachment={() => undefined}
                    onSubmit={() => undefined}
                    members={[BAKERY, PRIYA]}
                    user={{ email: 'dhruv@example.com' }}
                    textareaRef={ref}
                />
            );
        }
        // A laptop's box (jsdom has no media queries of its own).
        vi.stubGlobal('matchMedia', (query: string) => ({ matches: false, media: query, addEventListener: () => undefined, removeEventListener: () => undefined, addListener: () => undefined, removeListener: () => undefined }));
        render(
            <TooltipProvider>
                <Box />
            </TooltipProvider>
        );
        const box = screen.getByRole('textbox') as HTMLTextAreaElement;
        box.focus();
        fireEvent.change(box, { target: { value: '@What', selectionStart: 5, selectionEnd: 5 } });
        box.setSelectionRange(5, 5);
        fireEvent.select(box);
        const offered = screen.getByTestId('composer-suggestions');
        expect(offered.textContent).toContain('Bakery helper');
        expect(offered.textContent).toContain('formerly WhatsApp');
        fireEvent.keyDown(box, { key: 'Enter' });
        expect(box.value).toBe('@Bakery helper ');
    });
});
