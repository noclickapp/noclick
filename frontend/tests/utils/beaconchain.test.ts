// Checks the Beaconchain credential form and official icon metadata.
// Protects manual API-key connection and integration-directory placement.
import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { requirementsFromSchema, methodFromRequirement } from '~/components/credential/credentialMethods';
import schema from '~/schemas/nodes/beaconchain.json';

describe('Beaconchain credential and assets', () => {
  it('offers a manually pasted API key with a default type', () => {
    const method = methodFromRequirement(requirementsFromSchema(schema)[0]);
    expect(method.method_kind).toBe('api_key');
    const credential = schema.$defs.BeaconchainAPIKeyCredential;
    expect(credential.required).toEqual(['api_key']);
    expect(credential.properties.credential_type.default).toBe('beaconchain_api_key');
    expect(credential.properties.api_key['ui:widget']).toBe('password');
  });
  it('pins the official icon and categorizes the definition', () => {
    const icon = readFileSync('public/icons/beaconchain.svg');
    const provenance = JSON.parse(readFileSync('public/icons/beaconchain.svg.provenance.json', 'utf8'));
    expect(createHash('sha256').update(icon).digest('hex')).toBe(provenance.sha256);
    expect(provenance.source).toContain('gobitfly/beaconchain/');
    expect(readFileSync('app/components/workflow/nodes/integrations/beaconchain.tsx', 'utf8')).toContain("category: 'developer-tools'");
  });
});
