// Creem schema and definition regression coverage.
// Exercises the generated credential mapping and parent-dependent operation fields.
import { describe, expect, it } from 'vitest';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import schema from '~/schemas/nodes/creem.json';
import { CreemNode, CreemIcon } from '~/components/workflow/nodes/integrations/creem';
import { NODE_SCHEMAS, loadNodeSchemas, getNodeCredentialInfo, getAgentToolOperations } from '~/utils/nodeSchemas';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import { isAgentToolProviderType, isTriggerSource } from '~/utils/nodeMeta';

await loadNodeSchemas(['automation-creem']);

describe('native Creem schema, scopes, credential selection and exact official asset', () => {
    it('uses a native API key and fifteen operations with explicit write fields', () => {
        expect(NODE_SCHEMAS['automation-creem']).toBe(schema);
        expect(getNodeCredentialInfo('automation-creem')).toEqual({ providerKey: 'creem', acceptedTypes: ['creem_api_key'], label: 'Creem API Key' });
        expect(schema.$defs.CreemAPIKeyCredential.properties.credential_type.const).toBe('creem_api_key');
        expect(schema.$defs.CreemAPIKeyCredential.properties.api_key['ui:widget']).toBe('password');
        expect(schema.$defs.CreemAPIKeyCredential.properties.environment.enum).toEqual(['test', 'prod']);
        expect(schema.$defs.CreemAPIKeyCredential.required).toContain('api_key');
        expect(methodFromRequirement(requirementsFromSchema(schema)[0]).method_kind).toBe('api_key');
        const mapping = schema.properties.config.discriminator.mapping;
        expect(Object.keys(mapping)).toHaveLength(15);
        expect(Object.keys(mapping)).toEqual(expect.arrayContaining(['list_products', 'create_product', 'update_customer', 'archive_product', 'list_license_instances']));
        expect(schema.$defs.CreateProduct.required).toEqual(expect.arrayContaining(['name', 'description', 'price', 'currency', 'confirm_record_change']));
        expect(schema.$defs.CreateProduct.properties).not.toHaveProperty('billing_type');
        expect(schema.$defs.UpdateProduct.properties).not.toHaveProperty('price');
        expect(schema.$defs.GetSubscription.properties.subscription_id['x-dynamic-options'].depends_on).toBe('customer_id');
        expect(schema.$defs.ListLicenseInstances.properties.license_id['x-resource-type']).toBe('creem_license');
        expect(schema.$defs.ListLicenseInstances.properties.license_id['x-dynamic-options'].depends_on).toBe('customer_id');
        expect(isAgentToolProviderType(CreemNode.type)).toBe(true);
        expect(isTriggerSource(CreemNode.type, 'list_products')).toBe(false);
        const operation = getAgentToolOperations(CreemNode.type).find(op => op.operation === 'list_license_instances');
        expect(operation?.scopableFields).toEqual(expect.arrayContaining([expect.objectContaining({ field: 'license_id', dependsOn: 'customer_id', resourceType: 'creem_license' })]));
    });
    it('renders the exact official SVG', () => {
        expect(renderToStaticMarkup(createElement(CreemIcon))).toContain('/icons/creem.svg');
    });
});
