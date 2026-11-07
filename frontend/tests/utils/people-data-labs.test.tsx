// Real generated schema, discovered definition and credential method metadata.
// These assertions cover company-only credit controls and cannot establish live access.
import { beforeAll, describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import schema from '~/schemas/nodes/people-data-labs.json';
import { PeopleDataLabsNode } from '~/components/workflow/nodes/integrations/people-data-labs';
import { NODE_SCHEMAS, loadNodeSchemas, getNodeCredentialInfo } from '~/utils/nodeSchemas';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import { isAgentToolProviderType, isTriggerSource } from '~/utils/nodeMeta';

beforeAll(()=>loadNodeSchemas(['automation-people-data-labs']));

describe('native People Data Labs company workflows',()=>{
    it('keeps paid reads explicit and keeps connection checks separate from paid company operations',()=>{
        expect(NODE_SCHEMAS['automation-people-data-labs']).toBe(schema);
        expect(getNodeCredentialInfo('automation-people-data-labs')).toEqual({providerKey:'people_data_labs',acceptedTypes:['people_data_labs_api_key'],label:'People Data Labs API Key'});
        expect(schema.$defs.PeopleDataLabsAPIKeyCredential.properties.api_key['ui:widget']).toBe('password');
        expect(schema.$defs.PeopleDataLabsAPIKeyCredential.properties.credential_type.const).toBe('people_data_labs_api_key');
        expect(schema.$defs.PeopleDataLabsAPIKeyCredential).not.toHaveProperty('x-oauth-provider');
        expect(Object.keys(schema.properties.config.discriminator.mapping).sort()).toEqual(['check_connection','enrich_company','search_companies']);
        expect(schema.$defs.EnrichCompany.required).toContain('confirm_credit_use');
        expect(schema.$defs.SearchCompanies.required).toContain('confirm_credit_use');
        expect(schema.$defs.CheckConnection.properties).not.toHaveProperty('query');
        expect(schema.$defs.SearchCompanies.properties.size.maximum).toBe(100);
        expect(schema.$defs.SearchCompanies.properties).not.toHaveProperty('from');
        expect(schema.$defs.SearchCompanies.properties).not.toHaveProperty('scroll_token');
        expect(schema.$defs.EnrichCompany.properties.min_likelihood.default).toBe(6);
        expect(schema.$defs.EnrichCompany.properties).not.toHaveProperty('email');
        expect(isAgentToolProviderType(PeopleDataLabsNode.type)).toBe(true);
        expect(isTriggerSource(PeopleDataLabsNode.type,'search_companies')).toBe(false);
    });
    it('offers a masked API-key method with free Cleaner verification wording',()=>{
        const methods=requirementsFromSchema(schema).map(methodFromRequirement);
        expect(methods).toHaveLength(1);
        expect(methods[0]).toMatchObject({credential_type:'people_data_labs_api_key',method_kind:'api_key',is_oauth:false});
        expect(methods[0].credential_fields).toMatchObject([{name:'api_key',type:'password',required:true}]);
        expect(methods[0].instructions).toContain('free Company Cleaner API');
        expect(methods[0].instructions).toContain('Enrichment/search access and credits remain unverified');
    });
    it('renders the exact official public SVG',()=>{
        expect(renderToStaticMarkup(<PeopleDataLabsNode.Icon />)).toContain('/icons/people-data-labs.svg');
    });
});
