import { describe, expect, it } from 'vitest';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { loadNodeSchemas } from '~/utils/nodeSchemas';
import { ImageChartsNode } from '~/components/workflow/nodes/integrations/image-charts';

await loadNodeSchemas(['automation-image-charts']);

describe('Image-Charts manual connection', () => {
    it('offers the pasted Enterprise account ID and secret key', () => {
        const methods = credentialRequirements('automation-image-charts').map(methodFromRequirement);
        expect(methods).toHaveLength(1);
        expect(methods[0]).toMatchObject({ credential_type: 'image_charts_api_key', method_kind: 'api_key', is_oauth: false });
        const fields = methods[0].credential_fields.map(field => field.name);
        expect(fields).toEqual(expect.arrayContaining(['account_id', 'secret_key']));
    });
    it('lists in analytics and BI', () => {
        expect(ImageChartsNode.category).toBe('analytics-bi');
    });
});
