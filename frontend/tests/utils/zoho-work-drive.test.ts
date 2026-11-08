import { beforeAll, expect, it } from 'vitest';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { loadNodeSchemas } from '~/utils/nodeSchemas';
beforeAll(() => loadNodeSchemas(['automation-zoho-work-drive']));
import { ZohoWorkDriveNode } from '~/components/workflow/nodes/integrations/zoho-work-drive';

it('connects Zoho WorkDrive through the declared OAuth provider', () => {
    expect(ZohoWorkDriveNode.type).toBe('automation-zoho-work-drive');
    expect(ZohoWorkDriveNode.label).toBe('Zoho WorkDrive');
    const requirements = credentialRequirements(ZohoWorkDriveNode.type);
    expect(requirements).toHaveLength(1);
    expect(methodFromRequirement(requirements[0])).toMatchObject({
        credential_type: 'zoho_work_drive_oauth', method_kind: 'oauth',
        is_oauth: true, oauth_provider: 'zoho_work_drive',
    });
});
