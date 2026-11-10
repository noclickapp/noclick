// @vitest-environment happy-dom
import { beforeAll, expect, it } from 'vitest';
import { CanadaHolidaysNode } from '~/components/workflow/nodes/integrations/canada-holidays';
import { requirementsFromSchema } from '~/components/credential/credentialMethods';
import { loadNodeSchemas, NODE_SCHEMAS } from '~/utils/nodeSchemas';

beforeAll(() => loadNodeSchemas(['automation-canada-holidays']));

it('offers the public holiday API without a credential or sign-in method', async () => {
    const { hasUnconnectedCredentials } = await import('~/components/workflow/NodeCredentials');
    expect(CanadaHolidaysNode.category).toBe('content-research');
    expect(requirementsFromSchema(NODE_SCHEMAS[CanadaHolidaysNode.type])).toEqual([]);
    expect(hasUnconnectedCredentials(CanadaHolidaysNode.type, {})).toBe(false);
});
