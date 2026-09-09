// @vitest-environment jsdom

// The run-results "What came in" frame renders what a contact ATTACHED, not
// just what they typed — a WhatsApp voice note used to fall through to the raw
// JSON tree because the lead had no media slot (2026-09-09).
import { cleanup, render } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { InboundMessage } from '~/components/design/rehearsal/native';
import type { Scenario } from '~/components/design/rehearsal/fixture';

afterEach(cleanup);

const scenario = (slug: string, lead: Scenario['lead']): Scenario => ({
    slug,
    name: 'n',
    nodeName: 'n',
    triggerLabel: 'n',
    provider: 'generic',
    iconSlug: slug,
    key: `run:${slug}`,
    lead,
    events: [],
    doneAt: 0,
    artifacts: null,
} as unknown as Scenario);

describe('InboundMessage media', () => {
    it('plays a WhatsApp voice note inside the bubble', () => {
        const { container } = render(
            <InboundMessage
                scenario={scenario('whatsapp', {
                    title: '12025550102',
                    meta: '12025550102',
                    body: '',
                    handle: '12025550102',
                    media: { kind: 'audio', url: 'https://assets.example/v.oga', name: 'v.oga' },
                })}
            />
        );
        const audio = container.querySelector('audio');
        expect(audio?.getAttribute('src')).toBe('https://assets.example/v.oga');
        expect(container.querySelector('img')).toBeNull();
    });

    it('fills the bubble with a photo and keeps the caption beneath it', () => {
        const { container, getByText } = render(
            <InboundMessage
                scenario={scenario('whatsapp', {
                    title: 'Priya',
                    meta: '',
                    body: 'look at this',
                    author: 'Priya',
                    media: { kind: 'image', url: 'https://assets.example/p.jpg', name: 'p.jpg' },
                })}
            />
        );
        expect(container.querySelector('img')?.getAttribute('src')).toBe('https://assets.example/p.jpg');
        expect(getByText('look at this')).toBeTruthy();
    });

    it('names a document the browser cannot preview', () => {
        const { getByText, container } = render(
            <InboundMessage
                scenario={scenario('telegram', {
                    title: 'Sam',
                    meta: '',
                    body: '',
                    author: 'Sam',
                    media: { kind: 'file', name: 'deck.pdf' },
                })}
            />
        );
        expect(getByText('deck.pdf')).toBeTruthy();
        expect(container.querySelector('a')).toBeNull(); // no URL, no dead link
    });

    it('attaches media under a Slack row', () => {
        const { container } = render(
            <InboundMessage
                scenario={scenario('slack', {
                    title: '#ops',
                    meta: '#ops',
                    body: 'screenshot attached',
                    author: 'Dana',
                    media: { kind: 'image', url: 'https://assets.example/s.png' },
                })}
            />
        );
        expect(container.querySelector('img')?.getAttribute('src')).toBe('https://assets.example/s.png');
    });
});
