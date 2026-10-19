import { describe, expect, it } from 'vitest';
import { accountReference } from '~/components/shell/ComposerAddMenu';
import type { ConnectedAccount } from '~/components/shell/connections/accounts';
import { attachmentEcho } from '~/lib/agentChat';

const account = (app: string, line: string) => ({ credential: { id: 'cred-1' }, app, line, source: 'connected' }) as unknown as ConnectedAccount;

describe('accountReference', () => {
    it('names an account by its app and the account itself', () => {
        expect(accountReference(account('Slack', 'Acme workspace'))).toEqual({ kind: 'account', id: 'cred-1', label: 'Slack · Acme workspace' });
    });

    it('drops a line that says nothing more than the app or when it was added', () => {
        expect(accountReference(account('Linear', 'Linear')).label).toBe('Linear');
        expect(accountReference(account('Notion', 'Added Sep 2, 2026')).label).toBe('Notion');
    });
});

describe('attachmentEcho', () => {
    it('shows images as image content and other files as chips, the shapes a reload restores', () => {
        const echo = attachmentEcho([
            { resourceId: 'a', url: 'https://x/shot.png', name: 'shot.png', mimeType: 'image/png', sizeBytes: 1 },
            { resourceId: 'b', url: 'https://x/report.pdf', name: 'report.pdf', mimeType: 'application/pdf', sizeBytes: 2 },
        ]);
        expect(echo.content).toEqual([{ type: 'image_url', image_url: { url: 'https://x/shot.png' } }]);
        expect(echo.files).toEqual([{ name: 'report.pdf', url: 'https://x/report.pdf', mimeType: 'application/pdf' }]);
    });

    it('leaves both empty for no attachments', () => {
        expect(attachmentEcho([])).toEqual({ content: undefined, files: undefined });
    });
});
