import { createElement, type ElementType } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { AblyNode } from '~/components/workflow/nodes/integrations/ably';
import schema from '~/schemas/nodes/ably.json';

describe('Ably canvas node', () => {
    it('renders the official symbol and exposes the REST actions', () => {
        expect(AblyNode.type).toBe('automation-ably');
        expect(AblyNode.label).toBe('Ably');
        const html = renderToStaticMarkup(
            createElement(AblyNode.Icon as ElementType)
        );
        expect(html).toContain('/icons/ably.svg');

        expect(schema).toBeDefined();
        expect(Object.keys(schema.$defs ?? {}).length).toBeGreaterThan(32);
        expect(schema.properties?.credentials).toBeDefined();
    });
});
