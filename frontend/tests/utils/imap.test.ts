import { beforeAll, describe, expect, it } from 'vitest';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { ImapNode } from '~/components/workflow/nodes/integrations/imap';
import { loadNodeSchemas } from '~/utils/nodeSchemas';
import metadata from '~/schemas/nodeMeta/imap.json';

beforeAll(() => loadNodeSchemas(['automation-imap']));

describe('Email (IMAP/SMTP) connect form', () => {
    it('asks only for an address and an app password, with the servers under More options', () => {
        const [method] = credentialRequirements('automation-imap').map(methodFromRequirement);
        expect(method).toMatchObject({ credential_type: 'imap_smtp', method_kind: 'api_key' });
        const required = method.credential_fields.filter((f) => f.required).map((f) => [f.name, f.type]);
        expect(required).toEqual([['email', 'text'], ['password', 'password']]);
        const optional = method.credential_fields.filter((f) => !f.required).map((f) => f.name);
        expect(optional).toEqual(['imap_host', 'imap_port', 'imap_security', 'smtp_host', 'smtp_port', 'smtp_security', 'username']);
        const security = method.credential_fields.find((f) => f.name === 'smtp_security');
        expect(security?.default).toBe('auto');
        expect(security?.options?.map((o) => o.label)).toEqual(['Automatic (from the port)', 'SSL/TLS', 'STARTTLS']);
        expect(method.instructions).toContain('https://login.yahoo.com/account/security');
    });

    it('is a communication app with its trigger, findable by the providers it connects', () => {
        expect(ImapNode.category).toBe('communication');
        expect(metadata.nodeMeta).toMatchObject({ agentToolProvider: true, triggerOperations: ['on_new_email'] });
        expect(ImapNode.keywords).toEqual(expect.arrayContaining(['Yahoo Mail', 'iCloud Mail', 'Zoho Mail', 'SMTP']));
    });
});
