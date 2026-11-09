"""Starton Web3 automation with a pasted project API key.

Contract: starton-io/starton-openapi, version 1.0. Each operation makes one
request; lists return one page and transaction submissions are never retried.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client


class StartonAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Starton API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://app.starton.com/projects/default/developer",
            "x-credential-instructions": "Create an API key in your Starton project's developer settings and paste it here. The key can access your project; choose a project with the wallets and contracts your workflow needs.",
        })
    credential_type: Literal["starton_api_key"] = Field("starton_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, max_length=4096, repr=False,
                         json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if not isinstance(value, str) or not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without a header prefix or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("params", "metadata", "content", mode="before", check_fields=False)
    @classmethod
    def json_value(cls, value, info):
        if value is None:
            return value
        try:
            decoded = json.loads(value) if isinstance(value, str) else value
            expected = list if info.field_name == "params" else dict
            if not isinstance(decoded, expected):
                raise ValueError()
            if expected is list and any(not isinstance(item, (str, int, float, bool, dict)) for item in decoded):
                raise ValueError()
            return json.dumps(decoded, allow_nan=False)
        except (ValueError, TypeError):
            raise ValueError("Enter a JSON array of contract arguments" if info.field_name == "params" else "Enter a JSON object") from None


Segment = Annotated[str, Field(min_length=1, max_length=255, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")]
Address = Annotated[str, Field(pattern=r"^0x[0-9a-fA-F]{40}$")]



class StartonListTemplatesConfig(_Input):
    'Fetch the list of Smart Contract Templates'
    operation: Literal['list_templates'] = Field('list_templates', title='List Templates', json_schema_extra={"ui:hidden": True})
    page: int = Field(0, ge=0, le=1000000, description='Number of returned page. By default the returned page is the first.')
    limit: int = Field(100, ge=1, le=2500, description='Number of entities returned on each page. By default this number is set to 100.')
    isAudited: bool | None = Field(None)
    isActivated: bool | None = Field(None)
    blockchain: str | None = Field(None, max_length=8192)
    category: Literal['NFT', 'FUNGIBLE', 'OTHER', 'DEPRECATED', 'SALE', 'TOOL'] | None = Field(None)
    includeCompilationDetails: bool | None = Field(None)
    includeForm: bool | None = Field(None)


class StartonGetTemplateConfig(_Input):
    'Retrieve a Specific Smart Contract Template'
    operation: Literal['get_template'] = Field('get_template', title='Get Template', json_schema_extra={"ui:hidden": True})
    resource_id: Segment = Field(..., description='Unique identifier of the smart contract template.')
    includeForm: bool | None = Field(None)


class StartonListSmartContractsConfig(_Input):
    'Get all smart contracts'
    operation: Literal['list_smart_contracts'] = Field('list_smart_contracts', title='List Smart Contracts', json_schema_extra={"ui:hidden": True})
    page: int = Field(0, ge=0, le=1000000, description='Number of returned page. By default the returned page is the first.')
    limit: int = Field(100, ge=1, le=2500, description='Number of entities returned on each page. By default this number is set to 100.')
    network: str | None = Field(None, max_length=8192)
    address: Address | None = Field(None)
    includeAbi: bool | None = Field(None)
    includeCompilationDetails: bool | None = Field(None)


class StartonGetSmartContractConfig(_Input):
    'Get a single smart contract'
    operation: Literal['get_smart_contract'] = Field('get_smart_contract', title='Get Smart Contract', json_schema_extra={"ui:hidden": True})
    includeAbi: bool | None = Field(None)
    includeCompilationDetails: bool | None = Field(None)
    network: Segment = Field(..., description='EVM starton supported network.')
    address: Address = Field(..., description='Smart contract address.')


class StartonUpdateSmartContractConfig(_Input):
    'Update a smart contract'
    operation: Literal['update_smart_contract'] = Field('update_smart_contract', title='Update Smart Contract', json_schema_extra={"ui:hidden": True})
    network: Segment = Field(..., description='EVM starton supported network.')
    address: Address = Field(..., description='Smart contract address.')
    description: str | None = Field(None, max_length=8192)
    name: str | None = Field(None, max_length=255)
    metadata: str | None = Field(None, json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json", "contentMediaType": "application/json", "contentSchema": {"type": "object"}})


class StartonDeployFromTemplateConfig(_Input):
    'Deploy Smart Contract from Template'
    operation: Literal['deploy_from_template'] = Field('deploy_from_template', title='Deploy From Template', json_schema_extra={"ui:hidden": True})
    simulate: bool | None = Field(None, description='Boolean for transaction simulation. Will estimate gas price.')
    network: str = Field(..., max_length=8192, description='Network of the smart contract you want to deploy.')
    signerWallet: Address = Field(..., description='Signer wallet of the transaction.')
    templateId: str = Field(..., max_length=8192, description='Starton Library template to deploy.')
    name: str = Field(..., max_length=255, description='Contract name on Starton database (off-chain).')
    description: str | None = Field(None, max_length=8192, description='Contract description on Starton database (off-chain).')
    params: str = Field(..., description='Smart-contract arguments as a JSON array, in ABI order.', json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json", "contentMediaType": "application/json", "contentSchema": {"type": "array", "items": {"oneOf": [{"type": "string"}, {"type": "number"}, {"type": "object"}, {"type": "boolean"}]}}})
    gasLimit: str | None = Field(None, max_length=8192, description='Optional gas limit')
    speed: Literal['low', 'average', 'fast', 'fastest'] | None = Field(None, description='Gas speed. Starton defaults to average.')
    nonce: float | None = Field(None, description='Nonce manual setting, if nonce referenced, Starton relayer will not automaticly assign nonce.')
    value: str | None = Field(None, max_length=8192, description='If you want to put value in your smart contract deployment (Example: payable constructor)')
    metadata: str | None = Field(None, json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json", "contentMediaType": "application/json", "contentSchema": {"type": "object"}})


class StartonCallSmartContractConfig(_Input):
    'Execute Smart Contract Function'
    operation: Literal['call_smart_contract'] = Field('call_smart_contract', title='Call Smart Contract', json_schema_extra={"ui:hidden": True})
    network: Segment = Field(..., description='EVM starton supported network.')
    address: Address = Field(..., description='Smart contract address.')
    simulate: bool | None = Field(None, description='Boolean for transaction simulation. Will estimate gas price.')
    functionName: str = Field(..., max_length=8192)
    params: str = Field(..., description='Smart-contract arguments as a JSON array, in ABI order.', json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json", "contentMediaType": "application/json", "contentSchema": {"type": "array", "items": {"oneOf": [{"type": "string"}, {"type": "number"}, {"type": "object"}, {"type": "boolean"}]}}})
    speed: Literal['low', 'average', 'fast', 'fastest'] | None = Field(None)
    gasLimit: str | None = Field(None, max_length=8192)
    signerWallet: Address = Field(..., description='Existing Starton signerWallet.')
    nonce: float | None = Field(None)
    value: str | None = Field(None, max_length=8192)


class StartonReadSmartContractConfig(_Input):
    'Query Smart Contract Function'
    operation: Literal['read_smart_contract'] = Field('read_smart_contract', title='Read Smart Contract', json_schema_extra={"ui:hidden": True})
    network: Segment = Field(..., description='EVM starton supported network.')
    address: Address = Field(..., description='Smart contract address.')
    functionName: str = Field(..., max_length=8192)
    params: str | None = Field(None, description='Smart-contract arguments as a JSON array, in ABI order.', json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json", "contentMediaType": "application/json", "contentSchema": {"type": "array", "items": {"oneOf": [{"type": "string"}, {"type": "number"}, {"type": "object"}, {"type": "boolean"}]}}})


class StartonListTransactionsConfig(_Input):
    'Retrieve a List of Transactions'
    operation: Literal['list_transactions'] = Field('list_transactions', title='List Transactions', json_schema_extra={"ui:hidden": True})
    page: int = Field(0, ge=0, le=1000000, description='Number of returned page. By default the returned page is the first.')
    limit: int = Field(100, ge=1, le=2500, description='Number of entities returned on each page. By default this number is set to 100.')
    network: str | None = Field(None, max_length=8192, description="Specifies the network on which the transactions are deployed (filter). See <a href='https://docs.starton.com/docs/overview#supported-networks'>supported networks</a>.")
    transactionHash: str | None = Field(None, max_length=8192, description='The hash of a specific transaction (filter).')
    to: Address | None = Field(None, description='The address receiver of transactions, which can be a smart contract (filter).')
    from_address: Address | None = Field(None, description='The wallet used to sign the transactions (filter).')
    fromDate: datetime | None = Field(None, description='Retrieves transactions executed after a specified date.')


class StartonGetTransactionConfig(_Input):
    'Get a Specific Transaction'
    operation: Literal['get_transaction'] = Field('get_transaction', title='Get Transaction', json_schema_extra={"ui:hidden": True})
    resource_id: Segment = Field(..., description='Id of the transaction')


class StartonCreateTransactionConfig(_Input):
    'Create a new transaction'
    operation: Literal['create_transaction'] = Field('create_transaction', title='Create Transaction', json_schema_extra={"ui:hidden": True})
    simulate: bool | None = Field(None, description='Boolean for transaction simulation. Will estimate gas price.')
    data: str | None = Field(None, max_length=8192, description='Transaction data.')
    gasLimit: str | None = Field(None, max_length=8192)
    speed: Literal['low', 'average', 'fast', 'fastest'] | None = Field(None, description='Gas speed. Starton defaults to average.')
    metadata: str | None = Field(None, json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json", "contentMediaType": "application/json", "contentSchema": {"type": "object"}})
    network: str = Field(..., max_length=8192, description='Your network you want to perform transaction.')
    nonce: int | None = Field(None, description="Your transaction nonce. Don't fill this value if you want to use relayer nonce auto assignation.")
    signerWallet: Address = Field(..., description="Your kms address. It's also the from of your transaction.")
    to: Address | None = Field(None, description='The address you want to send to.')
    value: str | None = Field(None, max_length=8192, description='The value of the transaction in wei.')


class StartonListWalletsConfig(_Input):
    'Retrieve the list of Wallets'
    operation: Literal['list_wallets'] = Field('list_wallets', title='List Wallets', json_schema_extra={"ui:hidden": True})
    page: int = Field(0, ge=0, le=1000000, description='Number of returned page. By default the returned page is the first.')
    limit: int = Field(100, ge=1, le=2500, description='Number of entities returned on each page. By default this number is set to 100.')
    kmsId: str | None = Field(None, max_length=8192)


class StartonGetWalletConfig(_Input):
    'Fetch Wallet Details'
    operation: Literal['get_wallet'] = Field('get_wallet', title='Get Wallet', json_schema_extra={"ui:hidden": True})
    address: Address = Field(..., description='The address of the wallet.')


class StartonCreateWalletConfig(_Input):
    'Create a new wallet'
    operation: Literal['create_wallet'] = Field('create_wallet', title='Create Wallet', json_schema_extra={"ui:hidden": True})
    description: str | None = Field(None, max_length=8192)
    name: str | None = Field(None, max_length=8192)
    metadata: str | None = Field(None, json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json", "contentMediaType": "application/json", "contentSchema": {"type": "object"}})
    kmsId: str = Field(..., max_length=8192)


class StartonUpdateWalletConfig(_Input):
    'Update Wallet Information'
    operation: Literal['update_wallet'] = Field('update_wallet', title='Update Wallet', json_schema_extra={"ui:hidden": True})
    address: Address = Field(..., description='The address of the wallet to update.')
    description: str | None = Field(None, max_length=8192)
    name: str | None = Field(None, max_length=8192)
    metadata: str | None = Field(None, json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json", "contentMediaType": "application/json", "contentSchema": {"type": "object"}})


class StartonListKmsConfig(_Input):
    'Retrieve all Key Management Systems (KMS)'
    operation: Literal['list_kms'] = Field('list_kms', title='List KMS', json_schema_extra={"ui:hidden": True})
    page: int = Field(0, ge=0, le=1000000, description='Number of returned page. By default the returned page is the first.')
    limit: int = Field(100, ge=1, le=2500, description='Number of entities returned on each page. By default this number is set to 100.')


class StartonListNetworksConfig(_Input):
    'Retrieve the list of supported networks'
    operation: Literal['list_networks'] = Field('list_networks', title='List Networks', json_schema_extra={"ui:hidden": True})
    page: int = Field(0, ge=0, le=1000000, description='Number of returned page. By default the returned page is the first.')
    limit: int = Field(100, ge=1, le=2500, description='Number of entities returned on each page. By default this number is set to 100.')
    testnet: bool | None = Field(None)
    featured: bool | None = Field(None)
    deprecated: bool | None = Field(None)


class StartonGetNetworkConfig(_Input):
    'Fetch a specific network'
    operation: Literal['get_network'] = Field('get_network', title='Get Network', json_schema_extra={"ui:hidden": True})
    network: Segment = Field(..., description='The unique name of the network to retrieve')


class StartonGetGasPriceConfig(_Input):
    ' Retrieve the current gas prices'
    operation: Literal['get_gas_price'] = Field('get_gas_price', title='Get Gas Price', json_schema_extra={"ui:hidden": True})
    network: Segment = Field(..., description='The blockchain network you are checking gas prices on.')


class StartonListPinsConfig(_Input):
    'Retrieve all files'
    operation: Literal['list_pins'] = Field('list_pins', title='List Pins', json_schema_extra={"ui:hidden": True})
    page: int = Field(0, ge=0, le=1000000, description='Number of returned page. By default the returned page is the first.')
    limit: int = Field(100, ge=1, le=2500, description='Number of entities returned on each page. By default this number is set to 100.')
    cid: str | None = Field(None, max_length=8192)
    includeDirectoryContent: bool | None = Field(None)


class StartonGetPinConfig(_Input):
    'Retrieve a Specific File'
    operation: Literal['get_pin'] = Field('get_pin', title='Get Pin', json_schema_extra={"ui:hidden": True})
    resource_id: Segment = Field(..., description='The unique identifier of the file to be retrieved. This {id} is assigned when the file is initially uploaded to IPFS. ')
    includeDirectoryContent: bool | None = Field(None)


class StartonPinFileConfig(_Input):
    'Pin Existing IPFS File'
    operation: Literal['pin_file'] = Field('pin_file', title='Pin File', json_schema_extra={"ui:hidden": True})
    cid: str = Field(..., max_length=8192)
    name: str | None = Field(None, max_length=255)
    metadata: str | None = Field(None, json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json", "contentMediaType": "application/json", "contentSchema": {"type": "object"}})


class StartonUpdatePinConfig(_Input):
    'Update File Details'
    operation: Literal['update_pin'] = Field('update_pin', title='Update Pin', json_schema_extra={"ui:hidden": True})
    resource_id: Segment = Field(..., description='The unique identifier for the file you wish to update. This ID is assigned upon the initial upload of the file to IPFS.')
    name: str | None = Field(None, max_length=255)
    metadata: str | None = Field(None, json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json", "contentMediaType": "application/json", "contentSchema": {"type": "object"}})


class StartonDeletePinConfig(_Input):
    'Deletes pinned file referenced by {id}'
    operation: Literal['delete_pin'] = Field('delete_pin', title='Delete Pin', json_schema_extra={"ui:hidden": True})
    resource_id: Segment = Field(..., description='The unique identifier of the pinned file on Starton')


class StartonUploadJsonConfig(_Input):
    'Upload a JSON file'
    operation: Literal['upload_json'] = Field('upload_json', title='Upload JSON', json_schema_extra={"ui:hidden": True})
    name: str = Field(..., max_length=255)
    content: str = Field(..., description='JSON object to upload to IPFS.', json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json", "contentMediaType": "application/json", "contentSchema": {"type": "object"}})
    metadata: str | None = Field(None, json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json", "contentMediaType": "application/json", "contentSchema": {"type": "object"}})


StartonConfig = Annotated[
    Union[
        StartonListTemplatesConfig,
        StartonGetTemplateConfig,
        StartonListSmartContractsConfig,
        StartonGetSmartContractConfig,
        StartonUpdateSmartContractConfig,
        StartonDeployFromTemplateConfig,
        StartonCallSmartContractConfig,
        StartonReadSmartContractConfig,
        StartonListTransactionsConfig,
        StartonGetTransactionConfig,
        StartonCreateTransactionConfig,
        StartonListWalletsConfig,
        StartonGetWalletConfig,
        StartonCreateWalletConfig,
        StartonUpdateWalletConfig,
        StartonListKmsConfig,
        StartonListNetworksConfig,
        StartonGetNetworkConfig,
        StartonGetGasPriceConfig,
        StartonListPinsConfig,
        StartonGetPinConfig,
        StartonPinFileConfig,
        StartonUpdatePinConfig,
        StartonDeletePinConfig,
        StartonUploadJsonConfig,
    ],
    Field(discriminator="operation"),
]


class StartonFullConfig(NodeConfig[StartonConfig, StartonAPIKeyCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


ROUTES = {
    'list_templates': ('GET', '/v3/smart-contract-template', {'page': 'page', 'limit': 'limit', 'isAudited': 'isAudited', 'isActivated': 'isActivated', 'blockchain': 'blockchain', 'category': 'category', 'includeCompilationDetails': 'includeCompilationDetails', 'includeForm': 'includeForm'}, {}, {}),
    'get_template': ('GET', '/v3/smart-contract-template/{id}', {'includeForm': 'includeForm'}, {}, {'resource_id': 'id'}),
    'list_smart_contracts': ('GET', '/v3/smart-contract', {'page': 'page', 'limit': 'limit', 'network': 'network', 'address': 'address', 'includeAbi': 'includeAbi', 'includeCompilationDetails': 'includeCompilationDetails'}, {}, {}),
    'get_smart_contract': ('GET', '/v3/smart-contract/{network}/{address}', {'includeAbi': 'includeAbi', 'includeCompilationDetails': 'includeCompilationDetails'}, {}, {'network': 'network', 'address': 'address'}),
    'update_smart_contract': ('PATCH', '/v3/smart-contract/{network}/{address}', {}, {'description': 'description', 'name': 'name', 'metadata': 'metadata'}, {'network': 'network', 'address': 'address'}),
    'deploy_from_template': ('POST', '/v3/smart-contract/from-template', {'simulate': 'simulate'}, {'network': 'network', 'signerWallet': 'signerWallet', 'templateId': 'templateId', 'name': 'name', 'description': 'description', 'params': 'params', 'gasLimit': 'gasLimit', 'speed': 'speed', 'nonce': 'nonce', 'value': 'value', 'metadata': 'metadata'}, {}),
    'call_smart_contract': ('POST', '/v3/smart-contract/{network}/{address}/call', {'simulate': 'simulate'}, {'functionName': 'functionName', 'params': 'params', 'speed': 'speed', 'gasLimit': 'gasLimit', 'signerWallet': 'signerWallet', 'nonce': 'nonce', 'value': 'value'}, {'network': 'network', 'address': 'address'}),
    'read_smart_contract': ('POST', '/v3/smart-contract/{network}/{address}/read', {}, {'functionName': 'functionName', 'params': 'params'}, {'network': 'network', 'address': 'address'}),
    'list_transactions': ('GET', '/v3/transaction', {'page': 'page', 'limit': 'limit', 'network': 'network', 'transactionHash': 'transactionHash', 'to': 'to', 'from_address': 'from', 'fromDate': 'fromDate'}, {}, {}),
    'get_transaction': ('GET', '/v3/transaction/{id}', {}, {}, {'resource_id': 'id'}),
    'create_transaction': ('POST', '/v3/transaction', {'simulate': 'simulate'}, {'data': 'data', 'gasLimit': 'gasLimit', 'speed': 'speed', 'metadata': 'metadata', 'network': 'network', 'nonce': 'nonce', 'signerWallet': 'signerWallet', 'to': 'to', 'value': 'value'}, {}),
    'list_wallets': ('GET', '/v3/kms/wallet', {'page': 'page', 'limit': 'limit', 'kmsId': 'kmsId'}, {}, {}),
    'get_wallet': ('GET', '/v3/kms/wallet/{address}', {}, {}, {'address': 'address'}),
    'create_wallet': ('POST', '/v3/kms/wallet', {}, {'description': 'description', 'name': 'name', 'metadata': 'metadata', 'kmsId': 'kmsId'}, {}),
    'update_wallet': ('PATCH', '/v3/kms/wallet/{address}', {}, {'description': 'description', 'name': 'name', 'metadata': 'metadata'}, {'address': 'address'}),
    'list_kms': ('GET', '/v3/kms', {'page': 'page', 'limit': 'limit'}, {}, {}),
    'list_networks': ('GET', '/v3/network', {'page': 'page', 'limit': 'limit', 'testnet': 'testnet', 'featured': 'featured', 'deprecated': 'deprecated'}, {}, {}),
    'get_network': ('GET', '/v3/network/{name}', {}, {}, {'network': 'name'}),
    'get_gas_price': ('GET', '/v3/data/{network}/gas-price', {}, {}, {'network': 'network'}),
    'list_pins': ('GET', '/v3/ipfs/pin', {'page': 'page', 'limit': 'limit', 'cid': 'cid', 'includeDirectoryContent': 'includeDirectoryContent'}, {}, {}),
    'get_pin': ('GET', '/v3/ipfs/pin/{id}', {'includeDirectoryContent': 'includeDirectoryContent'}, {}, {'resource_id': 'id'}),
    'pin_file': ('POST', '/v3/ipfs/pin', {}, {'cid': 'cid', 'name': 'name', 'metadata': 'metadata'}, {}),
    'update_pin': ('PATCH', '/v3/ipfs/pin/{id}', {}, {'name': 'name', 'metadata': 'metadata'}, {'resource_id': 'id'}),
    'delete_pin': ('DELETE', '/v3/ipfs/pin/{id}', {}, {}, {'resource_id': 'id'}),
    'upload_json': ('POST', '/v3/ipfs/json', {}, {'name': 'name', 'content': 'content', 'metadata': 'metadata'}, {}),
}

LIST_OPERATIONS = frozenset(['list_templates', 'list_smart_contracts', 'list_transactions', 'list_wallets', 'list_kms', 'list_networks', 'list_pins'])


def _safe_output(value, secret):
    if isinstance(value, dict):
        return {k: _safe_output(v, secret) for k, v in value.items()
                if k.lower() not in {"apikey", "api_key", "x-api-key", "access_token", "refresh_token", "password", "privatekey", "private_key", "credentials", "secretaccesskey", "secret_access_key"}}
    if isinstance(value, list):
        return [_safe_output(v, secret) for v in value]
    return value.replace(secret, "[redacted]") if isinstance(value, str) else value


class StartonNode(WorkflowNode):
    integration_type = "automation-starton"
    connection_evidence = ConnectionEvidence(noun="smart contracts", operation="list_smart_contracts")

    @classmethod
    def get_config_model(cls):
        return StartonFullConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Starton API key")
        config = self.config.config
        secret = self.config.credentials.api_key
        values = config.model_dump(mode="json", exclude_none=True)
        for name in ("params", "metadata", "content"):
            if name in values:
                values[name] = json.loads(values[name])
        method, path, query_fields, body_fields, path_fields = ROUTES[config.operation]
        for name, wire in path_fields.items():
            path = path.replace("{" + wire + "}", quote(str(values[name]), safe=""))
        params = {wire: (str(values[name]).lower() if isinstance(values[name], bool) else values[name])
                  for name, wire in query_fields.items() if name in values}
        kwargs = {"params": params, "headers": {"x-api-key": secret, "Accept": "application/json"}}
        if body_fields:
            kwargs["json"] = {wire: values[name] for name, wire in body_fields.items() if name in values}
        try:
            async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
                response = await client.request(method, "https://api.starton.com" + path, **kwargs)
        except httpx.RequestError:
            raise ValueError("Starton request did not complete; check the provider before repeating a write") from None
        if not 200 <= response.status_code < 300:
            message = "Starton request failed"
            try:
                error = response.json()
                if isinstance(error, dict) and isinstance(error.get("message"), str):
                    message = error["message"][:2000]
            except ValueError:
                pass
            return {"status": "error", "http_status": response.status_code,
                    "message": _safe_output(message, secret)}
        if response.status_code == 204:
            data = None
        else:
            data = response.json()
            if not isinstance(data, bool if config.operation == "delete_pin" else dict):
                raise ValueError("Unexpected Starton response shape")
            if isinstance(data, dict) and (data.get("errorCode") or (isinstance(data.get("statusCode"), int) and data["statusCode"] >= 400)):
                return {"status": "error", "http_status": response.status_code,
                        "message": _safe_output(data.get("message", "Starton returned an error"), secret)}
        result = {"status": "success", "operation": config.operation, "data": _safe_output(data, secret)}
        if config.operation in LIST_OPERATIONS:
            if not isinstance(data, dict) or not isinstance(data.get("items"), list) or not isinstance(data.get("meta"), dict):
                raise ValueError("Unexpected Starton paginated response")
            result.update(items=_safe_output(data["items"], secret), meta=_safe_output(data["meta"], secret),
                          page=values["page"], limit=values["limit"])
        await self.emit(result)
        return result
