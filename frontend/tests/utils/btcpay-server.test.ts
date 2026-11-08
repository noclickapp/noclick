import { beforeAll, expect, it } from 'vitest';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { getNodeCredentialInfo, NODE_SCHEMAS, loadNodeSchemas } from '~/utils/nodeSchemas';
import { requirementsFromSchema, methodFromRequirement } from '~/components/credential/credentialMethods';
import { BtcpayServerNode } from '~/components/workflow/nodes/integrations/btcpay-server';

beforeAll(() => loadNodeSchemas(['automation-btcpay-server']));
it('discovers BTCPay Server with one pasted API key method and a server URL', () => {
    expect(BtcpayServerNode.type).toBe('automation-btcpay-server');
    expect(BtcpayServerNode.label).toBe('BTCPay Server');
    expect(BtcpayServerNode.category).toBe('finance-accounting');
    expect(getCredentialTypeFromSchemaTitle('Btcpay Server API Key')).toBe('btcpay_server_api_key');
    expect(getCredentialTypeFromSchemaTitle('BtcpayServerAPIKeyCredential')).toBe('btcpay_server_api_key');
    expect(getNodeCredentialInfo(BtcpayServerNode.type)?.acceptedTypes).toEqual(['btcpay_server_api_key']);
    const requirements = requirementsFromSchema(NODE_SCHEMAS[BtcpayServerNode.type]);
    expect(requirements).toHaveLength(1);
    const method = methodFromRequirement(requirements[0]);
    expect(method.method_kind).toBe('api_key');
    expect(method.is_oauth).toBe(false);
    expect(method.credential_fields?.map(field => field.name)).toEqual(['api_base_url', 'api_key']);
});
