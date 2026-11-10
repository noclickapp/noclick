// A credential type another integration borrows (borrowed_credential_types on its node class) wears its owner's
// mark and service, whatever order the two register in.
import { describe, expect, it } from 'vitest';
import { getAllSerializedNodeMeta } from '~/lib/nodeCatalog.server';
import { setNodeIconData } from '~/lib/nodeIconRegistry';
import { getServiceCredentialOptions } from '~/utils/credentialTypes';
import { borrowsCredentialType } from '~/utils/nodeMeta';
import { credentialMarks, NODE_SCHEMA_TYPES } from '~/utils/nodeSchemas';

const OWNERS: Array<[credentialType: string, owner: string, borrower: string]> = [
    ['reddit_oauth', 'automation-reddit', 'automation-reddit-ads'],
    ['microsoft_onedrive_oauth', 'automation-onedrive', 'automation-microsoft-powerpoint'],
    ['google_oauth', 'automation-google-classroom', 'automation-google-chat'],
];

describe('borrowed credential types', () => {
    it.each(OWNERS)('%s belongs to %s, not %s', (credentialType, owner, borrower) => {
        expect(borrowsCredentialType(borrower, credentialType)).toBe(true);
        expect(borrowsCredentialType(owner, credentialType)).toBe(false);
        // The borrower sorts first among self-registered integrations, so order alone would have handed it the type.
        expect(NODE_SCHEMA_TYPES.indexOf(borrower)).toBeLessThan(NODE_SCHEMA_TYPES.indexOf(owner));
        const marks = credentialMarks(() => true);
        expect([...marks].find(([, keys]) => keys.includes(credentialType))?.[0]).toBe(owner);
    });

    it('lists the owner as the service for a shared primary type', () => {
        setNodeIconData(getAllSerializedNodeMeta());
        const services = getServiceCredentialOptions().map((s) => s.value);
        for (const [, owner, borrower] of OWNERS) {
            expect(services).toContain(owner);
            expect(services).not.toContain(borrower);
        }
    });
});
