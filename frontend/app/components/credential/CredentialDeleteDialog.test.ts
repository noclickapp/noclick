// The delete confirmation names everything that loses the credential: the workflows whose
// steps use it, and what else holds it (a named connection, with what uses that, or an
// agent). Deleting the credential behind a connection once warned of nothing (2026-10-21).
import { describe, it, expect } from 'vitest';
import { credentialDeleteMessage } from './CredentialDeleteDialog';

const flow = (name: string) => ({ workflow_id: name, workflow_name: name });

describe('credentialDeleteMessage', () => {
    it('says nothing extra when nothing uses the credential', () => {
        expect(credentialDeleteMessage('WhatsApp', [], [])).toBeUndefined();
    });

    it('names the workflows that use it', () => {
        expect(credentialDeleteMessage('WhatsApp', [flow('Inbox')], [])).toBe(
            '"WhatsApp" is used by 1 workflow: Inbox. Deleting it will deactivate their triggers and break those nodes until you connect a new credential.',
        );
    });

    it('names the connections and agents that hold it, with what uses each connection', () => {
        const holders = [
            { kind: 'connection', id: 'c1', name: 'whatsapp', used_by: ['support', 'triage'] },
            { kind: 'agent', id: 'a1', name: 'research', used_by: [] },
        ];
        expect(credentialDeleteMessage('WhatsApp', [], holders)).toBe(
            'Deleting "WhatsApp" also disconnects the connection "whatsapp" (used by support, triage) and the agent "research" until it\'s reconnected.',
        );
        expect(credentialDeleteMessage('WhatsApp', [flow('Inbox')], holders.slice(0, 1))).toBe(
            '"WhatsApp" is used by 1 workflow: Inbox. Deleting it will deactivate their triggers and break those nodes until you connect a new credential. ' +
                'Deleting "WhatsApp" also disconnects the connection "whatsapp" (used by support, triage) until it\'s reconnected.',
        );
    });
});
