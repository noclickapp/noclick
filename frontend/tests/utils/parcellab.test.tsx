import { describe, expect, it } from 'vitest';
import { createElement, type ComponentType } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import schema from '~/schemas/nodes/parcellab.json';
import { ParcelLabNode } from '~/components/workflow/nodes/integrations/parcellab';
import { getNodeCredentialInfo, loadNodeSchemas } from '~/utils/nodeSchemas';
import { isAgentToolProviderType } from '~/utils/nodeMeta';

describe('parcelLab self registration', () => {
    it('discovers its token method and operation metadata', async () => {
        await loadNodeSchemas([ParcelLabNode.type]);
        expect(getNodeCredentialInfo(ParcelLabNode.type)).toEqual({
            providerKey: 'parcellab', acceptedTypes: ['parcellab_api_token'], label: 'parcelLab API Token',
        });
        expect(isAgentToolProviderType(ParcelLabNode.type)).toBe(true);
        expect(schema.$defs.Return.properties.return_id.format).toBe('uuid');
    });
    it('renders the local brand asset', () => {
        const html = renderToStaticMarkup(createElement(ParcelLabNode.Icon as ComponentType<{ className?: string }>));
        expect(html).toContain('/icons/parcellab-brand-vector.svg');
    });
});
