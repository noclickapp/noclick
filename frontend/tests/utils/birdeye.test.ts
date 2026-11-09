// Verify Birdeye's manual credential form and official brand asset.
// This keeps required business context and integration-directory placement visible.
import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { requirementsFromSchema, methodFromRequirement } from '~/components/credential/credentialMethods';
import schema from '~/schemas/nodes/birdeye.json';

describe('Birdeye connection', () => {
  it('offers an API key with manually supplied business ID', () => {
    expect(methodFromRequirement(requirementsFromSchema(schema)[0]).method_kind).toBe('api_key');
    expect(schema.$defs.BirdeyeAPIKeyCredential.required).toEqual(['api_key', 'business_id']);
    expect(schema.$defs.BirdeyeAPIKeyCredential.properties.credential_type.default).toBe('birdeye_api_key');
  });
  it('uses the official icon and marketing category', () => {
    const icon = readFileSync('public/icons/birdeye.png');
    const provenance = JSON.parse(readFileSync('public/icons/birdeye.png.provenance.json', 'utf8'));
    expect(createHash('sha256').update(icon).digest('hex')).toBe(provenance.sha256);
    expect(provenance.source).toContain('cdn2.birdeye.com');
    expect(readFileSync('app/components/workflow/nodes/integrations/birdeye.tsx', 'utf8')).toContain("category: 'marketing'");
  });
});
