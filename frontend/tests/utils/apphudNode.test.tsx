// Verify Apphud schema metadata, credential selection and the catalog icon.
// The tile base is mocked; these tests exercise its definition and native form schema.
import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { NODE_SCHEMAS, loadAllNodeSchemas, getNodeCredentialInfo, isAgentToolProviderType } from '~/utils/nodeSchemas';
import { getFieldsForOption } from '~/utils/schemaFieldExtractor';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { humanizeCredentialLabel } from '~/utils/credentialLabels';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { ApphudNode } from '~/components/workflow/nodes/integrations/apphud';

const socket = vi.hoisted(() => ({ send: vi.fn() }));
vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: socket.send }));
vi.mock('~/lib/indexeddb', () => ({ valtioCache: { get: vi.fn().mockResolvedValue(null), set: vi.fn().mockResolvedValue(undefined), delete: vi.fn() } }));
vi.mock('~/components/workflow/nodes/base/AutomationNode', () => ({ default: () => null }));
await loadAllNodeSchemas();
const type = 'automation-apphud';
const tag = 'apphud_s2s_api_key';

describe('Apphud native prepared source', () => {
    it('discovers the S2S header key and explicit app/chart authority', () => {
        const schema = NODE_SCHEMAS[type];
        expect(credentialRequirements(type).map(c => c.schema?.title)).toEqual(['Apphud App-level S2S API Key']);
        expect(getNodeCredentialInfo(type)?.acceptedTypes).toEqual([tag]);
        const credential = schema.$defs.ApphudAPIKeyCredential;
        expect(credential.properties.api_key['ui:widget']).toBe('password');
        expect(credential.required).toEqual(expect.arrayContaining(['api_key', 'app_id', 'allowed_operations']));
        expect(credential.properties.chart_ids.maxItems).toBe(40);
        expect(credential.properties.allowed_operations.maxItems).toBe(5);
        for (const field of ['api_base_url', 'access_token', 'password', 'refresh_token', 'customer_id', 'organization_id']) expect(credential.properties[field]).toBeUndefined();
        expect(credential['x-oauth-provider']).toBeUndefined();
        expect(credentialRequirements(type).map(req => methodFromRequirement(req).method_kind)).toEqual(['api_key']);
        expect(getCredentialTypeFromSchemaTitle('ApphudAPIKeyCredential')).toBe(tag);
        expect(getCredentialTypeFromSchemaTitle(credential.title)).toBe(tag);
        expect(humanizeCredentialLabel('ApphudAPIKey')).toBe('Apphud API Key');
    });

    it('keeps five closed reads and the actual chart-dependent filter form', () => {
        const schema = NODE_SCHEMAS[type];
        expect(Object.keys(schema.properties.config.discriminator.mapping).sort()).toEqual(['get_chart_options', 'get_filter_values', 'list_charts', 'query_column_chart', 'query_line_chart']);
        const fields = getFieldsForOption(type, undefined, 'get_filter_values');
        expect(fields.map(field => field.key)).toEqual(expect.arrayContaining(['chart_id', 'filter_id', 'filters']));
        expect(schema.$defs.ApphudGetFilterValuesConfig.properties.filter_id['x-dynamic-options'].depends_on).toEqual(['chart_id']);
        expect(schema.$defs.ApphudQueryLineChartConfig.properties.segments.maxItems).toBe(1);
        expect(schema.$defs.ApphudQueryColumnChartConfig.properties.segments.maxItems).toBe(2);
        expect(schema.$defs.ApphudPagination.properties.limit.maximum).toBe(2000);
        expect(schema.$defs.ApphudSorting.properties.order.enum).toEqual(['ASC', 'DESC']);
        expect(getFieldsForOption(type, undefined, 'list_charts').map(field => field.key)).not.toContain('chart_id');
        expect(schema.$defs.ApphudGetChartOptionsConfig.additionalProperties).toBe(false);
        expect(isAgentToolProviderType(type)).toBe(true);
    });

    it('wires the exact unchanged official nonauthenticated SVG', () => {
        const Icon = ApphudNode.Icon;
        expect(ApphudNode.type).toBe(type);
        expect(renderToStaticMarkup(<Icon />)).toContain('src="/icons/apphud-brand.svg"');
        expect(createHash('sha256').update(readFileSync(resolve(__dirname, '../../public/icons/apphud.svg'))).digest('hex')).toBe('57ad21502701ad7beb830086998accc5ee3dd2ea98a186dacdd9d8d56648f17f');
    });
});
