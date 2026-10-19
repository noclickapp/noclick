// @vitest-environment jsdom
// A recording or a video NoClick links the way it links an image (`![Call recording](…mp3)`) plays in place, as the
// phone channels deliver it as native media; only an image renders as one.
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { MarkdownRenderer } from '~/components/chat/MarkdownRenderer';
import { embedKindOf } from '~/lib/embedKind';

afterEach(cleanup);

const CALL_NOTE =
    'The call completed, but it reached a voicemail greeting saying the mailbox hasn’t been set up yet. The caller said “Hi” and the call ended.\n\n' +
    '![Call recording](https://assets.example.test/u1/account/r1/call-2026-10-06-120609.mp3)';

describe('embedKindOf', () => {
    it('reads the kind from the file name, ignoring a query', () => {
        expect(embedKindOf('https://assets.example.test/u/a/call.mp3')).toBe('audio');
        expect(embedKindOf('https://x.test/note.M4A?sig=abc')).toBe('audio');
        expect(embedKindOf('https://x.test/clip.webm#t=2')).toBe('video');
        expect(embedKindOf('https://x.test/photo.png')).toBe('image');
        expect(embedKindOf('https://x.test/download?file=call.mp3')).toBe('image');
    });
});

describe('MarkdownRenderer', () => {
    it('plays a call recording in place instead of drawing a broken image', () => {
        const { container } = render(<MarkdownRenderer content={CALL_NOTE} />);
        expect(container.querySelector('img')).toBeNull();
        const card = screen.getByTestId('coordinator-recording');
        expect(screen.getByText('Call recording')).toBeTruthy();
        expect(screen.getByRole('button', { name: 'Play' })).toBeTruthy();
        // A player is a block: never inside a paragraph.
        expect(card.closest('p')).toBeNull();
        expect(screen.getByText(/reached a voicemail greeting/).tagName).toBe('P');
    });

    it('plays a video and keeps an image an image', () => {
        const { container } = render(<MarkdownRenderer content={'![Teaser](https://x.test/teaser.mp4)\n\n![Logo](https://x.test/logo.png)'} />);
        expect(container.querySelector('video')?.getAttribute('src')).toBe('https://x.test/teaser.mp4');
        expect(container.querySelector('img')?.getAttribute('alt')).toBe('Logo');
    });
});
