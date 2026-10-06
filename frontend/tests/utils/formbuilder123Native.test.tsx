// @vitest-environment jsdom
import { render, cleanup } from '@testing-library/react';
import { afterEach, expect, it } from 'vitest';
import { FormBuilder123Node } from '~/components/workflow/nodes/FormBuilder123Node';
import { NODE_SCHEMAS, getNodeCredentialInfo } from '~/utils/nodeSchemas';
import { CREDENTIAL_TYPE_MAP } from '~/utils/credentialTypeMap';
import { humanizeCredentialLabel } from '~/utils/credentialLabels';
import { collectCredentialAlternatives } from '~/utils/credentialSchemaAlternatives';

afterEach(cleanup);
it('uses the native single v2 credential, scoped parent schema and current display label', () => {
    const schema: any = NODE_SCHEMAS['automation-123formbuilder'];
    const alternatives = collectCredentialAlternatives(schema);
    expect(alternatives.map(a => a.schema.properties.credential_type.const)).toEqual(['123formbuilder_v2_token']);
    expect(CREDENTIAL_TYPE_MAP.FormBuilder123TokenCredential).toBe('123formbuilder_v2_token');
    expect(getNodeCredentialInfo('automation-123formbuilder')?.acceptedTypes).toEqual(['123formbuilder_v2_token']);
    expect(getNodeCredentialInfo('automation-123formbuilder')?.label).toBe('123FormBuilder Account');
    expect(humanizeCredentialLabel('FormBuilder123TokenCredential')).toBe('123FormBuilder Token Credential');
    const ops = Object.values(schema.$defs) as any[];
    const read = ops.find(d => d.properties?.operation?.const === 'get_form_field');
    expect(read.properties.field_id['x-dynamic-options'].depends_on).toBe('form_id');
    expect(schema.$defs.FormBuilder123TokenCredential.properties.token['ui:widget']).toBe('password');
    expect(schema.$defs.FormBuilder123TokenCredential['x-oauth-provider']).toBeUndefined();
});

it('renders the same checked-in exact vendor vector used by the node definition', () => {
    const { container } = render(<FormBuilder123Node.Icon />);
    expect(container.querySelector('img')?.getAttribute('src')).toBe('/icons/123formbuilder.svg');
    expect(FormBuilder123Node.label).toBe('123FormBuilder');
});
