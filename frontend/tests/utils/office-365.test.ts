// Office 365 webhook operations must reach both workflows and the agent trigger picker.
// Pins the generated metadata and keeps subscription setup fields out of the form.
import { describe, expect, it } from 'vitest';
import schema from '../../app/schemas/nodes/office-365.json';
import metadata from '../../app/schemas/nodeMeta/office-365.json';

describe('office-365 triggers', () => {
    it('advertises the inbox and configurable Outlook triggers', () => {
        expect(metadata.nodeMeta.triggerOperations).toEqual(['on_new_message', 'on_outlook_change']);
        const triggers = Object.values(schema.$defs).filter((definition) =>
            'properties' in definition && 'operation' in definition.properties &&
            'x-is-trigger' in definition.properties.operation && definition.properties.operation['x-is-trigger']);
        expect(triggers).toHaveLength(2);
        for (const trigger of triggers) {
            expect(trigger).toHaveProperty('x-requires-webhook', true);
            expect(trigger).toHaveProperty('properties.webhook_url.ui:loadValue', true);
            expect(trigger).toHaveProperty('properties.signing_secret.ui:hidden', true);
            expect(trigger).toHaveProperty('properties.external_webhook_id.ui:hidden', true);
        }
    });
});
