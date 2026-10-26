// @vitest-environment jsdom
// A recording, a video or any other file NoClick links the way it links an image (`![Call recording](…mp3)`,
// `![Briefing](…pdf)`) plays in place or shows as a file card, as the phone channels deliver it as native media or a
// document; only an image renders as one.
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeAll, describe, expect, it } from 'vitest';
import { MarkdownRenderer } from '~/components/chat/MarkdownRenderer';
import { embedKindOf, fileKindOf, fileNameOf, previewType } from '~/lib/embedKind';

// A card loads the preview with the first file opened; load it up front so a click here opens it at once.
beforeAll(() => import('~/components/dashboard/FilePreviewDialog'), 120_000);
afterEach(cleanup);

const CALL_NOTE =
    'The call completed, but it reached a voicemail greeting saying the mailbox hasn’t been set up yet. The caller said “Hi” and the call ended.\n\n' +
    '![Call recording](https://assets.example.test/u1/account/r1/call-2026-10-06-120609.mp3)';

// A briefing the coordinator made, as it embeds it: the stored name, percent-encoded, ends in its extension.
const BRIEFING_URL =
    'https://assets.example.test/9b2d7c1e-0000-4000-8000-000000000001/account/5f3a1b2c-0000-4000-8000-000000000002/Lisbon%20%E2%80%93%20site%20visit%20%7C%20briefing.pdf';
const BRIEFING = `Here’s your briefing for tomorrow.\n\n![Lisbon site visit briefing PDF](${BRIEFING_URL})`;

describe('embedKindOf', () => {
    it('reads the kind from the file name, ignoring a query', () => {
        expect(embedKindOf('https://assets.example.test/u/a/call.mp3')).toBe('audio');
        expect(embedKindOf('https://x.test/note.M4A?sig=abc')).toBe('audio');
        expect(embedKindOf('https://x.test/clip.webm#t=2')).toBe('video');
        expect(embedKindOf('https://x.test/photo.png')).toBe('image');
        expect(embedKindOf('https://x.test/download?file=call.mp3')).toBe('image');
    });

    it('makes every document, sheet, deck, text file and archive a file', () => {
        for (const ext of ['pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'csv', 'txt', 'md', 'json', 'html', 'zip', 'rtf', 'odt']) {
            expect(embedKindOf(`https://assets.example.test/u/account/r/report.${ext}`), ext).toBe('file');
        }
    });

    it('reads the extension in any case, past a query or fragment, and under an encoded name', () => {
        expect(embedKindOf('https://x.test/Report.PDF')).toBe('file');
        expect(embedKindOf('https://x.test/Deck.PptX?X-Amz-Signature=abc&X-Amz-Expires=3600')).toBe('file');
        expect(embedKindOf('https://x.test/notes.txt#page=2')).toBe('file');
        expect(embedKindOf(BRIEFING_URL)).toBe('file');
        expect(embedKindOf('https://x.test/Photo%20%E2%80%93%20shelf.JPEG?w=800')).toBe('image');
    });

    it('keeps a picture a picture when its URL names no extension, or a name with dots and digits only', () => {
        expect(embedKindOf('https://images.example.test/photo-1520975922284?w=1200&q=80')).toBe('image');
        expect(embedKindOf('https://x.test/Screenshot%202026-10-26%20at%2010.30.45')).toBe('image');
        expect(embedKindOf('https://x.test/media/')).toBe('image');
    });

    it('takes a named file of a type it doesn’t list as a file, not a broken picture', () => {
        expect(embedKindOf('https://x.test/invite.ics')).toBe('file');
        expect(embedKindOf('https://x.test/IMG_0042.HEIC')).toBe('file');
    });
});

describe('a file’s name and kind', () => {
    it('decodes the name a URL ends in, and keeps one that isn’t valid percent-encoding as written', () => {
        expect(fileNameOf(BRIEFING_URL)).toBe('Lisbon – site visit | briefing.pdf');
        expect(fileNameOf('https://x.test/a/50%off.pdf?sig=1')).toBe('50%off.pdf');
        expect(fileNameOf('/staff-lab/invoice-0419.pdf')).toBe('invoice-0419.pdf');
    });

    it('sorts by extension into the kinds Resources draws', () => {
        expect(fileKindOf('briefing.pdf')).toBe('doc');
        expect(fileKindOf('deck.pptx')).toBe('doc');
        expect(fileKindOf('ledger.XLSX')).toBe('data');
        expect(fileKindOf('site.zip')).toBe('archive');
        expect(fileKindOf('index.html')).toBe('code');
        expect(fileKindOf('folder.v2/README')).toBe('other');
    });

    it('previews a PDF or a picture always, text only at a size it can hold, and nothing else', () => {
        expect(previewType('briefing.pdf', null)).toBe('application/pdf');
        expect(previewType('shelf.jpg', null)).toBe('image/jpg');
        expect(previewType('notes.md', 2048)).toBe('text/markdown');
        expect(previewType('notes.md', null)).toBeNull();
        expect(previewType('huge.csv', 10 * 1024 * 1024)).toBeNull();
        expect(previewType('ledger.xlsx', 2048)).toBeNull();
        expect(previewType('site.zip', 2048)).toBeNull();
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

    it('draws a PDF as a file card under its caption, which opens the PDF in the preview', async () => {
        const { container } = render(<MarkdownRenderer content={BRIEFING} />);
        expect(container.querySelector('img')).toBeNull();
        const card = screen.getByTestId('agent-chat-file-attachment');
        expect(card.textContent).toContain('Lisbon site visit briefing PDF');
        expect(card.textContent).toContain('PDF');
        expect(card.getAttribute('href')).toBe(BRIEFING_URL);
        // A card is a block: never inside a paragraph.
        expect(card.closest('p')).toBeNull();

        card.focus();
        fireEvent.click(card);
        const preview = await screen.findByTestId('dashboard-file-preview');
        expect(within(preview).getByText('Lisbon – site visit | briefing.pdf')).toBeTruthy();
        expect(preview.querySelector('iframe')?.getAttribute('src')).toBe(BRIEFING_URL);
        expect(within(preview).getByRole('link', { name: /Download/ }).getAttribute('href')).toBe(BRIEFING_URL);
        // It came with no size or time, so the preview names none.
        expect(preview.textContent).not.toMatch(/\b0 B\b|NaN/);

        // Closed, it hands focus back to the card that opened it.
        fireEvent.keyDown(preview, { key: 'Escape' });
        await waitFor(() => expect(screen.queryByTestId('dashboard-file-preview')).toBeNull());
        expect(document.activeElement).toBe(card);
    });

    it('downloads a file the preview can’t show, and names it by the file when there is no caption', () => {
        render(<MarkdownRenderer content={'Your numbers:\n\n![](https://assets.example.test/u/account/r/Q3%20ledger.xlsx)'} />);
        const card = screen.getByTestId('agent-chat-file-attachment');
        expect(card.textContent).toContain('Q3 ledger.xlsx');
        expect(card.textContent).toContain('XLSX');
        expect(card.getAttribute('download')).toBe('Q3 ledger.xlsx');
        fireEvent.click(card);
        expect(screen.queryByTestId('dashboard-file-preview')).toBeNull();
    });
});
