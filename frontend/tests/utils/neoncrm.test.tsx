// Unrun native Neon CRM registration, credential discovery and selection checks.
// Uses the real schema and palette consumers with mocked storage/socket boundaries.
// The original vector is rendered as an image; this is not a live canvas capture.
import { describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { createElement } from 'react';
import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
const mocks = vi.hoisted(() => ({ send: vi.fn(), get: vi.fn(), set: vi.fn(), del: vi.fn() }));
vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: mocks.send }));
vi.mock('~/lib/indexeddb', () => ({ valtioCache: { get: mocks.get, set: mocks.set, delete: mocks.del } }));
import schema from '~/schemas/nodes/neoncrm.json';
import { NeonCRMIcon, NeonCRMNode } from '~/components/workflow/nodes/integrations/neoncrm';
import { AVAILABLE_NODES } from '~/components/workflow/nodes/nodeRegistry';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import { getNodeCredentialInfo, filterConfigForExecution, loadAllNodeSchemas } from '~/utils/nodeSchemas';
import { getAvailableOperations } from '~/utils/operationHelpers';
import { invalidateCredentialsCache } from '~/utils/credentialAutoSelect';
import { autoSelectCredential, autoSelectCredentialFromCache } from '~/utils/credentialAutoSelectForNode';
import { buildNodeSearchIndexEntry, getNodeSearchScore } from '~/utils/nodeSearchMatch';
import { scoreNodeService } from '~/utils/nodeServiceSearch';
import { isAgentToolProviderType } from '~/utils/nodeMeta';

await loadAllNodeSchemas();

describe('native Neon CRM', () => {
    it('registers useful native operations and credential form metadata', () => {
        expect(AVAILABLE_NODES.find(n => n.type === 'automation-neoncrm')).toBe(NeonCRMNode);
        expect(getAvailableOperations('automation-neoncrm').map(o => o.value).sort()).toEqual(["create_activity","create_company_account","create_contact","create_individual_account","delete_activity","delete_contact","get_account","get_activity","get_contact","get_current_user","get_event","get_organization_profile","list_accounts","list_activity_output_fields","list_activity_search_fields","list_activity_statuses","list_activity_types","list_contacts","list_events","list_timezones","search_activities","update_activity","update_company_account","update_contact","update_individual_account"]);
        expect(getNodeCredentialInfo('automation-neoncrm')?.acceptedTypes).toEqual(['neoncrm_api_key']);
        const credential = schema.$defs.NeonCRMAPIKeyCredential;
        expect(requirementsFromSchema(schema).map(req => methodFromRequirement(req).method_kind)).toEqual(['api_key']);
        expect(credential.title).toBe('Neon CRM API Key');
        expect(credential.properties.api_key['ui:widget']).toBe('password');
        expect(Object.keys(credential.properties)).toEqual(expect.arrayContaining(['credential_type', 'org_id', 'api_key', 'instance']));
        expect(isAgentToolProviderType('automation-neoncrm')).toBe(true);
    });

    it('keeps Neon CRM findable in both palettes', () => {
        expect(getNodeSearchScore(buildNodeSearchIndexEntry(NeonCRMNode), 'neoncrm')).not.toBeNull();
        expect(scoreNodeService({ nodeType: NeonCRMNode.type, ...NeonCRMNode }, 'tool', 'neoncrm')).not.toBeNull();
    });

    it('renders the exact official asset with a fixed path', () => {
        const html = renderToStaticMarkup(createElement(NeonCRMIcon, { src: '/wrong.svg' } as any));
        expect(html).toContain('src="/icons/neoncrm.svg"');
        expect(html).toContain('object-fit:contain');
        const bytes = readFileSync(new URL('../../public/icons/neoncrm.svg', import.meta.url));
        expect(createHash('sha256').update(bytes).digest('hex')).toBe('1053888252aea57a90beba6b43d70309f1303621138b72df6c206bf79e6eb0cf');
    });

    it('filters stale mutation fields while preserving platform metadata', () => {
        const filtered = filterConfigForExecution('automation-neoncrm', {
            operation: 'get_current_user', account_id: '11', first_name: 'stale', metadata: 'platform',
        });
        expect(filtered).not.toHaveProperty('account_id');
        expect(filtered).not.toHaveProperty('first_name');
        expect(filtered.metadata).toBe('platform');
    });

    it('selects and caches the actual native credential family', async () => {
        invalidateCredentialsCache();
        mocks.get.mockResolvedValue(null);
        mocks.set.mockResolvedValue(undefined);
        mocks.send.mockResolvedValue({ credentials: [
            { id: 'foreign', credential_type: 'other_api_key', updated_at: '2026-10-06T12:00:00Z' },
            { id: 'native', credential_type: 'neoncrm_api_key', updated_at: '2026-10-06T11:00:00Z' },
        ] });
        expect(await autoSelectCredential('automation-neoncrm')).toEqual({ neoncrm_api_key: 'native' });
        expect(autoSelectCredentialFromCache('automation-neoncrm')).toEqual({ neoncrm_api_key: 'native' });
        expect(mocks.send).toHaveBeenCalledWith(expect.objectContaining({ event_name: 'credential:list' }));
    });
});
