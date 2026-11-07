import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { NODE_SCHEMAS, filterConfigForExecution, getNodeCredentialInfo, isAgentToolProviderType, loadNodeSchemas } from '~/utils/nodeSchemas';
import { requirementsFromSchema, methodFromRequirement } from '~/components/credential/credentialMethods';
import { INTEGRATION_METADATA } from '~/utils/integrationMetadata';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { humanizeCredentialLabel } from '~/utils/credentialLabels';
import { PolarNode } from '~/components/workflow/nodes/integrations/polar';

vi.mock('~/components/workflow/nodes/base/AutomationNode', () => ({ default: () => null }));
const type = 'automation-polar';
const tag = 'polar_organization_access_token';
await loadNodeSchemas([type]);

describe('Polar integration', () => {
    it('discovers the distinct OAT method, explicit environment and private token', () => {
        const schema = NODE_SCHEMAS[type];
        expect(requirementsFromSchema(schema).map(c => c.schema?.title)).toEqual(['Polar Organization Access Token']);
        expect(getNodeCredentialInfo(type)?.acceptedTypes).toEqual([tag]);
        const def = schema.$defs.PolarOrganizationAccessTokenCredential;
        expect(def.properties.credential_type.const).toBe(tag);
        expect(def.properties.organization_access_token['ui:widget']).toBe('password');
        expect(def.properties.environment.enum).toEqual(['sandbox', 'production']);
        expect(def.properties.environment.default).toBeUndefined();
        expect(def.required).toEqual(expect.arrayContaining(['organization_access_token', 'environment', 'organization_id', 'declared_scopes', 'allowed_operations']));
        expect(getCredentialTypeFromSchemaTitle(def.title)).toBe(tag);
        expect(getCredentialTypeFromSchemaTitle('PolarOrganizationAccessTokenCredential')).toBe(tag);
        expect(humanizeCredentialLabel(def.title)).toBe(def.title);
        for (const field of ['client_secret', 'refresh_token', 'api_base_url', 'customer_session_token']) expect(def.properties[field]).toBeUndefined();
        expect(def['x-oauth-provider']).toBeUndefined();
    });

    it('registers one token method with automatic credential selection', () => {
        const requirements = requirementsFromSchema(NODE_SCHEMAS[type]);
        expect(requirements).toHaveLength(1);
        const method = methodFromRequirement(requirements[0]);
        expect(method.credential_type).toBe(tag);
        expect(method.method_kind).toBe('api_key');
        expect(method.is_oauth).toBe(false);
        expect(INTEGRATION_METADATA.autoSelectTypes).toContain(type);
    });

    it('preserves exact operations, parent chain, cascade confirmations and execution filtering', () => {
        const schema = NODE_SCHEMAS[type];
        const operations = Object.keys(schema.properties.config.discriminator.mapping);
        expect(operations).toHaveLength(22);
        expect(operations).toEqual(expect.arrayContaining(['create_draft_product', 'create_draft_custom_benefit', 'delete_customer', 'list_subscriptions', 'get_order']));
        for (const op of ['create_order', 'refund_order', 'cancel_subscription', 'grant_benefit', 'create_checkout', 'create_webhook', 'publish_product']) expect(operations).not.toContain(op);
        expect(schema.$defs.PolarGetOrderConfig.properties.order_id['x-dynamic-options'].depends_on).toBe('customer_id');
        expect(schema.$defs.PolarGetOrderConfig.properties.customer_id['x-dynamic-options'].depends_on).toBe('organization_id');
        expect(schema.$defs.PolarDeleteCustomerConfig.properties.confirm_cascade.const).toBe(true);
        expect(schema.$defs.PolarDeleteBenefitConfig.properties.confirm_revoke.const).toBe(true);
        expect(schema.$defs.PolarResourceBinding.properties.owned_disposable.default).toBe(false);
        expect(filterConfigForExecution(type, { operation: 'update_customer_metadata', organization_id: 'org', customer_id: 'customer', metadata: { flag: true }, confirm_effects: true, email: 'discard' })).toEqual({ operation: 'update_customer_metadata', organization_id: 'org', customer_id: 'customer', metadata: { flag: true }, confirm_effects: true });
        expect(isAgentToolProviderType(type)).toBe(true);
    });

    it('wires the official vector artwork to the native tile', () => {
        const Icon = PolarNode.Icon;
        expect(PolarNode.type).toBe(type);
        expect(renderToStaticMarkup(<Icon />)).toContain('src="/icons/polar-brand-vector.svg"');
        expect(createHash('sha256').update(readFileSync(resolve(__dirname, '../../public/icons/polar-brand-vector.svg'))).digest('hex')).toBe('bd294b3ee3af00a4342eb85dfba4c38d395ad3ecb1d9b63aa5fcf1112edc9571');
    });
});
