// @vitest-environment happy-dom
import { render, cleanup } from '@testing-library/react';
import { afterEach, expect, it } from 'vitest';
import { FormBuilder123Node } from '~/components/workflow/nodes/FormBuilder123Node';
import { NODE_SCHEMAS, getNodeCredentialInfo, loadNodeSchemas } from '~/utils/nodeSchemas';
import { CREDENTIAL_TYPE_MAP } from '~/utils/credentialTypeMap';

afterEach(cleanup);
it('uses the native single v2 credential and scoped parent schema', async () => {
    await loadNodeSchemas(['automation-123formbuilder']);
    const schema: any = NODE_SCHEMAS['automation-123formbuilder'];
    expect(schema.$defs.FormBuilder123TokenCredential.properties.credential_type.const).toBe('123formbuilder_v2_token');
    expect(CREDENTIAL_TYPE_MAP.FormBuilder123TokenCredential).toBe('123formbuilder_v2_token');
    expect(getNodeCredentialInfo('automation-123formbuilder')?.acceptedTypes).toEqual(['123formbuilder_v2_token']);
    expect(getNodeCredentialInfo('automation-123formbuilder')?.label).toBe('123FormBuilder Account');
    const ops = Object.values(schema.$defs) as any[];
    const read = ops.find(d => d.properties?.operation?.const === 'get_form_field');
    expect(read.properties.field_id['x-dynamic-options'].depends_on).toBe('form_id');
    expect(schema.$defs.FormBuilder123TokenCredential.properties.token['ui:widget']).toBe('password');
    expect(schema.$defs.FormBuilder123TokenCredential['x-oauth-provider']).toBeUndefined();
});

it('renders the same checked-in exact vendor vector used by the node definition', () => {
    const { container } = render(<FormBuilder123Node.Icon />);
    expect(container.querySelector('img')?.getAttribute('src')).toBe('/icons/123formbuilder-brand-vector.svg');
    expect(FormBuilder123Node.label).toBe('123FormBuilder');
});
