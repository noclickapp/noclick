"""Spydra Asset Tokenization API v1.0.0: network-scoped assets and approvals.

Each operation makes one documented request; bookmarks and receipts are returned
unchanged for explicit continuation and transaction-status checks.
"""
from __future__ import annotations

import re
import httpx
from typing import Annotated, Any, Literal, Optional, Union
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import SSRFError, guarded_async_client


class SpydraAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Spydra API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://docs.spydra.app/developers/api-key",
            "x-credential-instructions": "In your Spydra Network, open API Keys and create or copy an API key. Paste the network's Asset Tokenization REST API base URL, including /tokenize/<chaincodeccid>, from the app's REST API page. The key is network-specific. NoClick sends it as X-API-KEY to this deployment; use only your trusted Spydra deployment URL.",
        })
    credential_type: Literal["spydra_api_key"] = Field("spydra_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API key", json_schema_extra={"ui:widget": "password"})
    api_url: str = Field(..., title="REST API base URL", description="Your network deployment URL: https://<membership_id>.spydra.app/tokenize/<app_id>")

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key", key=True)
        if any(ch.isspace() or ord(ch) < 33 for ch in value):
            raise ValueError("Paste the API key without spaces or a header prefix")
        return value

    @field_validator("api_url", mode="before")
    @classmethod
    def base_url(cls, value):
        if not isinstance(value, str):
            raise ValueError("Paste your deployment's REST API base URL")
        value = value.strip().rstrip("/")
        parts = urlsplit(value)
        if (parts.scheme != "https" or not parts.hostname or parts.username is not None
                or parts.password is not None or parts.port is not None or parts.query or parts.fragment
                or not re.fullmatch(r"[a-zA-Z0-9-]+\.spydra\.app", parts.hostname)
                or not re.fullmatch(r"/tokenize/[A-Za-z0-9_-]+", parts.path)):
            raise ValueError("Use https://<membership_id>.spydra.app/tokenize/<app_id> without a query or fragment")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class SpydraEntity(BaseModel):
    # Spydra explicitly permits userId, vendorId or another entity key.
    model_config = ConfigDict(extra="allow", hide_input_in_errors=True)
    orgId: str = Field(..., min_length=1, description="Membership ID of the organization.")
    userId: Optional[str] = None


class SpydraOwnershipChange(_Input):
    id: str = Field(..., min_length=1, description="Asset ID.")
    owners: list[SpydraEntity] = Field(..., min_length=1, max_length=100)


class SpydraApprovalRequest(_Input):
    approvers: list[SpydraEntity] = Field(..., min_length=1, max_length=100)
    numRequired: Optional[float] = Field(None, gt=0, description="Number of approvers required.")
    timeout: Optional[float] = Field(None, gt=0, description="Timeout in minutes.")
    data: Optional[dict[str, Any]] = None


class SpydraApprovalAction(_Input):
    id: str = Field(..., min_length=1, description="Approval request ID.")
    comment: Optional[str] = Field(None, max_length=4096)


class SpydraCreateAssetsConfig(_Input):
    'Create an asset or a list of assets.'
    operation: Literal['create_assets'] = Field('create_assets', json_schema_extra={"ui:hidden": True})
    async_mode: bool = Field(False, description="Return a receipt immediately instead of waiting for ledger commit.")
    assetType: str = Field(..., description='The type of asset defined in the Asset Tokenization App settings.', min_length=1, max_length=4096)
    data: list[dict[str, Any]] = Field(..., description='Custom JSON object representing an asset. You can submit a single asset or multiple assets in one request by providing an array of assets here.', min_length=1, max_length=100)

class SpydraUpsertAssetsConfig(_Input):
    'Create or update an asset or a list of assets. If an asset with the same id exists, the existing asset will be updated.'
    operation: Literal['upsert_assets'] = Field('upsert_assets', json_schema_extra={"ui:hidden": True})
    async_mode: bool = Field(False, description="Return a receipt immediately instead of waiting for ledger commit.")
    assetType: str = Field(..., description='The type of asset defined in the Asset Tokenization App settings.', min_length=1, max_length=4096)
    data: list[dict[str, Any]] = Field(..., description='Custom JSON object representing an asset. You can submit a single asset or multiple assets in one request by providing an array of assets here.', min_length=1, max_length=100)

class SpydraGetAssetConfig(_Input):
    'Query an asset.'
    operation: Literal['get_asset'] = Field('get_asset', json_schema_extra={"ui:hidden": True})
    assetType: str = Field(..., description='The type of asset defined in the Asset Tokenization App settings.', min_length=1, max_length=4096)
    id: str = Field(..., description='Id of the asset. This is the Id that is maintained in your system and corresponds to value of the Primary Key attribute defined in the Asset Tokenization App settings.', min_length=1, max_length=4096)
    depth: Optional[int] = Field(None, description='For referenced objects, depth up to which references to be returned. For e.g. if depth=1, one level of references will be resolved.', ge=0, le=10)
    actAs: Optional[str] = Field(None, description='The entity (like user, suborg etc) within the org on behalf of which the request is being made.\n\n*Example:* userId:123', min_length=1, max_length=4096)

class SpydraUpdateAssetsConfig(_Input):
    'Update an asset or a list of assets.'
    operation: Literal['update_assets'] = Field('update_assets', json_schema_extra={"ui:hidden": True})
    async_mode: bool = Field(False, description="Return a receipt immediately instead of waiting for ledger commit.")
    actAs: Optional[str] = Field(None, description='The entity (like user, suborg etc) within the org on behalf of which the request is being made.\n\n*Example:* userId:123', min_length=1, max_length=4096)
    assetType: str = Field(..., description='The type of asset defined in the Asset Tokenization App settings.', min_length=1, max_length=4096)
    data: list[dict[str, Any]] = Field(..., description='Custom JSON object representing an asset. You can submit a single asset or multiple assets in one request by providing an array of assets here.', min_length=1, max_length=100)

class SpydraDeleteAssetsConfig(_Input):
    'Delete one or more assets.'
    operation: Literal['delete_assets'] = Field('delete_assets', json_schema_extra={"ui:hidden": True})
    async_mode: bool = Field(False, description="Return a receipt immediately instead of waiting for ledger commit.")
    actAs: Optional[str] = Field(None, description='The entity (like user, suborg etc) within the org on behalf of which the request is being made.\n\n*Example:* userId:123', min_length=1, max_length=4096)
    assetType: str = Field(..., description='The type of asset defined in the Asset Tokenization App settings.', min_length=1, max_length=4096)
    id: list[str] = Field(..., description='Id of the asset. This is the Id that is maintained in your system and corresponds to the value of the Primary Key attribute defined in the Asset Tokenization App settings. You can submit a single id or multiple Ids in one request by providing an array here.', min_length=1, max_length=100)

class SpydraUpdateAssetOwnersConfig(_Input):
    'Update owners of an asset. This method replaces the current owners with the new owner array provided.'
    operation: Literal['update_asset_owners'] = Field('update_asset_owners', json_schema_extra={"ui:hidden": True})
    async_mode: bool = Field(False, description="Return a receipt immediately instead of waiting for ledger commit.")
    actAs: Optional[str] = Field(None, description='The entity (like user, suborg etc) within the org on behalf of which the request is being made.\n\n*Example:* userId:123', min_length=1, max_length=4096)
    assetType: str = Field(..., description='The type of asset defined in the Asset Tokenization App settings.', min_length=1, max_length=4096)
    data: list[SpydraOwnershipChange] = Field(..., description='Ownership change data. Supports ownership change for single asset or bulk change for an array of assets.', min_length=1, max_length=100)

class SpydraGetAssetHistoryConfig(_Input):
    'Get the asset along with history of changes.'
    operation: Literal['get_asset_history'] = Field('get_asset_history', json_schema_extra={"ui:hidden": True})
    assetType: str = Field(..., description='The type of asset defined in the Asset Tokenization App settings.', min_length=1, max_length=4096)
    id: str = Field(..., description='Id of the asset. This is the Id that is maintained in your system and corresponds to the value of the Primary Key attribute defined in the Asset Tokenization App settings.', min_length=1, max_length=4096)
    depth: Optional[int] = Field(None, description='For referenced objects, depth up to which references to be returned.', ge=0, le=10)
    actAs: Optional[str] = Field(None, description='The entity (like user, suborg etc) within the org on behalf of which the request is being made.\n\n*Example:* userId:123', min_length=1, max_length=4096)

class SpydraListAssetsConfig(_Input):
    'Get all assets.'
    operation: Literal['list_assets'] = Field('list_assets', json_schema_extra={"ui:hidden": True})
    assetType: str = Field(..., description='The type of asset defined in the Asset Tokenization App settings.', min_length=1, max_length=4096)
    pageSize: Optional[int] = Field(None, description='The number of records to be returned in a page. The default is 25.', ge=1, le=1000)
    bookmark: Optional[str] = Field(None, description='The bookmark returned by previous request.', min_length=1, max_length=4096)
    actAs: Optional[str] = Field(None, description='The entity (like user, suborg etc) within the org on behalf of which the request is being made.\n\n*Example:* userId:123', min_length=1, max_length=4096)

class SpydraGetReceiptConfig(_Input):
    'Get the status of an already submitted transaction using the returned receipt id.'
    operation: Literal['get_receipt'] = Field('get_receipt', json_schema_extra={"ui:hidden": True})
    receiptId: str = Field(..., description='The receipt id returned while submitting the transaction.', min_length=1, max_length=4096)

class SpydraGetAssetStatsConfig(_Input):
    'Get statistics about asset usage.'
    operation: Literal['get_asset_stats'] = Field('get_asset_stats', json_schema_extra={"ui:hidden": True})

class SpydraGetTransferRequestConfig(_Input):
    'Get ownership transfer request by id.'
    operation: Literal['get_transfer_request'] = Field('get_transfer_request', json_schema_extra={"ui:hidden": True})
    id: str = Field(..., description='Id of the ownership approval request.', min_length=1, max_length=4096)
    actAs: Optional[str] = Field(None, description='The entity (like user, suborg etc) within the org on behalf of which the request is being made.\n\n*Example:* userId:123', min_length=1, max_length=4096)

class SpydraApproveTransferRequestsConfig(_Input):
    'Approve ownership transfer request.'
    operation: Literal['approve_transfer_requests'] = Field('approve_transfer_requests', json_schema_extra={"ui:hidden": True})
    async_mode: bool = Field(False, description="Return a receipt immediately instead of waiting for ledger commit.")
    actAs: Optional[str] = Field(None, description='The entity (like user, suborg etc) within the org on behalf of which the request is being made.\n\n*Example:* userId:123', min_length=1, max_length=4096)
    id: list[str] = Field(..., description='Id of the approval request. You can approve multiple ownership transfer requests together by providing an array of Ids here.', min_length=1, max_length=100)

class SpydraRejectTransferRequestsConfig(_Input):
    'Reject ownership transfer request.'
    operation: Literal['reject_transfer_requests'] = Field('reject_transfer_requests', json_schema_extra={"ui:hidden": True})
    async_mode: bool = Field(False, description="Return a receipt immediately instead of waiting for ledger commit.")
    actAs: Optional[str] = Field(None, description='The entity (like user, suborg etc) within the org on behalf of which the request is being made.\n\n*Example:* userId:123', min_length=1, max_length=4096)
    id: list[str] = Field(..., description='Id of the approval request. You can approve multiple ownership transfer requests together by providing an array of Ids here.', min_length=1, max_length=100)

class SpydraListMyTransferRequestsConfig(_Input):
    'Get the status of ownership transfer requests submitted by an entity.'
    operation: Literal['list_my_transfer_requests'] = Field('list_my_transfer_requests', json_schema_extra={"ui:hidden": True})
    pageSize: Optional[int] = Field(None, description='The number of records to be returned in a page. The default is 25.', ge=1, le=1000)
    bookmark: Optional[str] = Field(None, description='The bookmark returned by previous request.', min_length=1, max_length=4096)
    actAs: Optional[str] = Field(None, description='The entity (like user, suborg etc) within the org on behalf of which the request is being made.\n\n*Example:* userId:123', min_length=1, max_length=4096)

class SpydraListTransferApprovalsConfig(_Input):
    'Get the ownership transfer requests in queue for approval.'
    operation: Literal['list_transfer_approvals'] = Field('list_transfer_approvals', json_schema_extra={"ui:hidden": True})
    onlyPending: Optional[bool] = Field(None, description='Get only pending requests. The default is true.')
    pageSize: Optional[int] = Field(None, description='The number of records to be returned in a page. The default is 25.', ge=1, le=1000)
    bookmark: Optional[str] = Field(None, description='The bookmark returned by previous request.', min_length=1, max_length=4096)
    actAs: Optional[str] = Field(None, description='The entity (like user, suborg etc) within the org on behalf of which the request is being made.\n\n*Example:* userId:123', min_length=1, max_length=4096)

class SpydraCreateApprovalsConfig(_Input):
    'Create a new approval request.'
    operation: Literal['create_approvals'] = Field('create_approvals', json_schema_extra={"ui:hidden": True})
    async_mode: bool = Field(False, description="Return a receipt immediately instead of waiting for ledger commit.")
    actAs: Optional[str] = Field(None, description='The entity (like user, suborg etc) within the org on behalf of which the request is being made.\n\n*Example:* userId:123', min_length=1, max_length=4096)
    approvalType: str = Field(..., description='A unique name that represents this type of approval. The type is used to distinguish between different types of approvals in the systems. For e.g. LoanRequestApproval and LoanDisbursementApproval can be different approval types in the system. The type is also required while making other Approval API related calls.', min_length=1, max_length=4096)
    approvals: list[SpydraApprovalRequest] = Field(..., description='The Approval request related data. Multiple approvals can be submitted together by providing an array here.', min_length=1, max_length=100)

class SpydraGetApprovalConfig(_Input):
    'Get approval request by id.'
    operation: Literal['get_approval'] = Field('get_approval', json_schema_extra={"ui:hidden": True})
    id: str = Field(..., description='Id of the approval request.', min_length=1, max_length=4096)
    approvalType: str = Field(..., description='A unique name that represents this type of approval. The type is used to distinguish between different types of approvals in the systems. For e.g. LoanRequestApproval and LoanDisbursementApproval can be different approval types in the system. The type is also required while making other Approval API related calls.\n\n*Example:* LoanRequestApproval', min_length=1, max_length=4096)
    actAs: Optional[str] = Field(None, description='The entity (like user, suborg etc) within the org on behalf of which the request is being made.\n\n*Example:* userId:123', min_length=1, max_length=4096)

class SpydraAcceptApprovalsConfig(_Input):
    'Approve the request.'
    operation: Literal['accept_approvals'] = Field('accept_approvals', json_schema_extra={"ui:hidden": True})
    async_mode: bool = Field(False, description="Return a receipt immediately instead of waiting for ledger commit.")
    actAs: Optional[str] = Field(None, description='The entity (like user, suborg etc) within the org on behalf of which the request is being made.\n\n*Example:* userId:123', min_length=1, max_length=4096)
    approvalType: str = Field(..., description='A unique name that represents this type of approval. The type is used to distinguish between different types of approvals in the systems. For e.g. LoanRequestApproval and LoanDisbursementApproval can be different approval types in the system. The type is also required while making other Approval API related calls.', min_length=1, max_length=4096)
    approvals: list[SpydraApprovalAction] = Field(..., description='The Approval request related data. Multiple approvals can be submitted together by providing an array here.', min_length=1, max_length=100)

class SpydraRejectApprovalsConfig(_Input):
    'Reject approval request.'
    operation: Literal['reject_approvals'] = Field('reject_approvals', json_schema_extra={"ui:hidden": True})
    async_mode: bool = Field(False, description="Return a receipt immediately instead of waiting for ledger commit.")
    actAs: Optional[str] = Field(None, description='The entity (like user, suborg etc) within the org on behalf of which the request is being made.\n\n*Example:* userId:123', min_length=1, max_length=4096)
    approvalType: str = Field(..., description='A unique name that represents this type of approval. The type is used to distinguish between different types of approvals in the systems. For e.g. LoanRequestApproval and LoanDisbursementApproval can be different approval types in the system. The type is also required while making other Approval API related calls.', min_length=1, max_length=4096)
    approvals: list[SpydraApprovalAction] = Field(..., description='The Approval request related data. Multiple approvals can be submitted together by providing an array here.', min_length=1, max_length=100)

class SpydraCancelApprovalsConfig(_Input):
    'Cancel approval request.'
    operation: Literal['cancel_approvals'] = Field('cancel_approvals', json_schema_extra={"ui:hidden": True})
    async_mode: bool = Field(False, description="Return a receipt immediately instead of waiting for ledger commit.")
    actAs: Optional[str] = Field(None, description='The entity (like user, suborg etc) within the org on behalf of which the request is being made.\n\n*Example:* userId:123', min_length=1, max_length=4096)
    approvalType: str = Field(..., description='A unique name that represents this type of approval. The type is used to distinguish between different types of approvals in the systems. For e.g. LoanRequestApproval and LoanDisbursementApproval can be different approval types in the system. The type is also required while making other Approval API related calls.', min_length=1, max_length=4096)
    approvals: list[SpydraApprovalAction] = Field(..., description='The Approval request related data. Multiple approvals can be submitted together by providing an array here.', min_length=1, max_length=100)

class SpydraListMyApprovalsConfig(_Input):
    'Get the status of approval requests submitted by an entity.'
    operation: Literal['list_my_approvals'] = Field('list_my_approvals', json_schema_extra={"ui:hidden": True})
    approvalType: str = Field(..., description='A unique name that represents this type of approval. The type is used to distinguish between different types of approvals in the systems. For e.g. LoanRequestApproval and LoanDisbursementApproval can be different approval types in the system. The type is also required while making other Approval API related calls.\n\n*Example:* LoanRequestApproval', min_length=1, max_length=4096)
    pageSize: Optional[int] = Field(None, description='The number of records to be returned in a page. The default is 25.', ge=1, le=1000)
    bookmark: Optional[str] = Field(None, description='The bookmark returned by previous request.', min_length=1, max_length=4096)
    actAs: Optional[str] = Field(None, description='The entity (like user, suborg etc) within the org on behalf of which the request is being made.\n\n*Example:* userId:123', min_length=1, max_length=4096)

class SpydraListApprovalQueueConfig(_Input):
    'Get the approval requests in queue for approval.'
    operation: Literal['list_approval_queue'] = Field('list_approval_queue', json_schema_extra={"ui:hidden": True})
    approvalType: str = Field(..., description='A unique name that represents this type of approval. The type is used to distinguish between different types of approvals in the systems. For e.g. LoanRequestApproval and LoanDisbursementApproval can be different approval types in the system. The type is also required while making other Approval API related calls.\n\n*Example:* LoanRequestApproval', min_length=1, max_length=4096)
    onlyPending: Optional[bool] = Field(None, description='Get only pending requests. The default is true.')
    pageSize: Optional[int] = Field(None, description='The number of records to be returned in a page. The default is 25.', ge=1, le=1000)
    bookmark: Optional[str] = Field(None, description='The bookmark returned by previous request.', min_length=1, max_length=4096)
    actAs: Optional[str] = Field(None, description='The entity (like user, suborg etc) within the org on behalf of which the request is being made.\n\n*Example:* userId:123', min_length=1, max_length=4096)

class SpydraGetApprovalHistoryConfig(_Input):
    'Get the approval requests for a particular asset.'
    operation: Literal['get_approval_history'] = Field('get_approval_history', json_schema_extra={"ui:hidden": True})
    id: str = Field(..., description='Id of the approval request.', min_length=1, max_length=4096)
    approvalType: str = Field(..., description='A unique name that represents this type of approval. The type is used to distinguish between different types of approvals in the systems. For e.g. LoanRequestApproval and LoanDisbursementApproval can be different approval types in the system. The type is also required while making other Approval API related calls.\n\n*Example:* LoanRequestApproval', min_length=1, max_length=4096)
    actAs: Optional[str] = Field(None, description='The entity (like user, suborg etc) within the org on behalf of which the request is being made.\n\n*Example:* userId:123', min_length=1, max_length=4096)

SpydraConfig = Annotated[Union[
    SpydraCreateAssetsConfig,
    SpydraUpsertAssetsConfig,
    SpydraGetAssetConfig,
    SpydraUpdateAssetsConfig,
    SpydraDeleteAssetsConfig,
    SpydraUpdateAssetOwnersConfig,
    SpydraGetAssetHistoryConfig,
    SpydraListAssetsConfig,
    SpydraGetReceiptConfig,
    SpydraGetAssetStatsConfig,
    SpydraGetTransferRequestConfig,
    SpydraApproveTransferRequestsConfig,
    SpydraRejectTransferRequestsConfig,
    SpydraListMyTransferRequestsConfig,
    SpydraListTransferApprovalsConfig,
    SpydraCreateApprovalsConfig,
    SpydraGetApprovalConfig,
    SpydraAcceptApprovalsConfig,
    SpydraRejectApprovalsConfig,
    SpydraCancelApprovalsConfig,
    SpydraListMyApprovalsConfig,
    SpydraListApprovalQueueConfig,
    SpydraGetApprovalHistoryConfig
], Field(discriminator="operation")]


class SpydraFullConfig(NodeConfig[SpydraConfig, SpydraAPIKeyCredential]):
    pass


OPERATIONS = {'create_assets': {'method': 'POST',
                   'path': '/asset',
                   'query': [('async_mode', 'async')],
                   'body': ['assetType', 'data'],
                   'statuses': [201, 202]},
 'upsert_assets': {'method': 'PUT',
                   'path': '/asset',
                   'query': [('async_mode', 'async')],
                   'body': ['assetType', 'data'],
                   'statuses': [201, 202]},
 'get_asset': {'method': 'GET',
               'path': '/asset',
               'query': [('assetType', 'assetType'),
                         ('id', 'id'),
                         ('depth', 'depth'),
                         ('actAs', 'actAs')],
               'body': [],
               'statuses': [200]},
 'update_assets': {'method': 'PATCH',
                   'path': '/asset',
                   'query': [('async_mode', 'async'), ('actAs', 'actAs')],
                   'body': ['assetType', 'data'],
                   'statuses': [200, 202]},
 'delete_assets': {'method': 'DELETE',
                   'path': '/asset',
                   'query': [('async_mode', 'async'), ('actAs', 'actAs')],
                   'body': ['assetType', 'id'],
                   'statuses': [200, 202]},
 'update_asset_owners': {'method': 'PATCH',
                         'path': '/asset/owners',
                         'query': [('async_mode', 'async'), ('actAs', 'actAs')],
                         'body': ['assetType', 'data'],
                         'statuses': [200, 202]},
 'get_asset_history': {'method': 'GET',
                       'path': '/asset/history',
                       'query': [('assetType', 'assetType'),
                                 ('id', 'id'),
                                 ('depth', 'depth'),
                                 ('actAs', 'actAs')],
                       'body': [],
                       'statuses': [200]},
 'list_assets': {'method': 'GET',
                 'path': '/asset/all',
                 'query': [('assetType', 'assetType'),
                           ('pageSize', 'pageSize'),
                           ('bookmark', 'bookmark'),
                           ('actAs', 'actAs')],
                 'body': [],
                 'statuses': [200]},
 'get_receipt': {'method': 'GET',
                 'path': '/asset/receipt',
                 'query': [('receiptId', 'receiptId')],
                 'body': [],
                 'statuses': [200]},
 'get_asset_stats': {'method': 'GET',
                     'path': '/asset/stats',
                     'query': [],
                     'body': [],
                     'statuses': [200]},
 'get_transfer_request': {'method': 'GET',
                          'path': '/asset/ownershipTransfer/request',
                          'query': [('id', 'id'), ('actAs', 'actAs')],
                          'body': [],
                          'statuses': [200]},
 'approve_transfer_requests': {'method': 'POST',
                               'path': '/asset/ownershipTransfer/approve',
                               'query': [('async_mode', 'async'), ('actAs', 'actAs')],
                               'body': ['id'],
                               'statuses': [200, 202]},
 'reject_transfer_requests': {'method': 'POST',
                              'path': '/asset/ownershipTransfer/reject',
                              'query': [('async_mode', 'async'), ('actAs', 'actAs')],
                              'body': ['id'],
                              'statuses': [200, 202]},
 'list_my_transfer_requests': {'method': 'GET',
                               'path': '/asset/ownershipTransfer/request/my',
                               'query': [('pageSize', 'pageSize'),
                                         ('bookmark', 'bookmark'),
                                         ('actAs', 'actAs')],
                               'body': [],
                               'statuses': [200]},
 'list_transfer_approvals': {'method': 'GET',
                             'path': '/asset/ownershipTransfer/request/approvals',
                             'query': [('onlyPending', 'onlyPending'),
                                       ('pageSize', 'pageSize'),
                                       ('bookmark', 'bookmark'),
                                       ('actAs', 'actAs')],
                             'body': [],
                             'statuses': [200]},
 'create_approvals': {'method': 'POST',
                      'path': '/approval',
                      'query': [('async_mode', 'async'), ('actAs', 'actAs')],
                      'body': ['approvalType', 'approvals'],
                      'statuses': [200, 202]},
 'get_approval': {'method': 'GET',
                  'path': '/approval',
                  'query': [('id', 'id'), ('approvalType', 'approvalType'), ('actAs', 'actAs')],
                  'body': [],
                  'statuses': [200]},
 'accept_approvals': {'method': 'POST',
                      'path': '/approval/accept',
                      'query': [('async_mode', 'async'), ('actAs', 'actAs')],
                      'body': ['approvalType', 'approvals'],
                      'statuses': [200, 202]},
 'reject_approvals': {'method': 'POST',
                      'path': '/approval/reject',
                      'query': [('async_mode', 'async'), ('actAs', 'actAs')],
                      'body': ['approvalType', 'approvals'],
                      'statuses': [200, 202]},
 'cancel_approvals': {'method': 'POST',
                      'path': '/approval/cancel',
                      'query': [('async_mode', 'async'), ('actAs', 'actAs')],
                      'body': ['approvalType', 'approvals'],
                      'statuses': [200, 202]},
 'list_my_approvals': {'method': 'GET',
                       'path': '/approval/my',
                       'query': [('approvalType', 'approvalType'),
                                 ('pageSize', 'pageSize'),
                                 ('bookmark', 'bookmark'),
                                 ('actAs', 'actAs')],
                       'body': [],
                       'statuses': [200]},
 'list_approval_queue': {'method': 'GET',
                         'path': '/approval/queue',
                         'query': [('approvalType', 'approvalType'),
                                   ('onlyPending', 'onlyPending'),
                                   ('pageSize', 'pageSize'),
                                   ('bookmark', 'bookmark'),
                                   ('actAs', 'actAs')],
                         'body': [],
                         'statuses': [200]},
 'get_approval_history': {'method': 'GET',
                          'path': '/approval/history',
                          'query': [('id', 'id'),
                                    ('approvalType', 'approvalType'),
                                    ('actAs', 'actAs')],
                          'body': [],
                          'statuses': [200]}}


class SpydraNode(WorkflowNode):
    integration_type = "automation-spydra"
    connection_evidence = ConnectionEvidence(noun="ownership transfer requests", operation="list_my_transfer_requests")

    @classmethod
    def get_config_model(cls):
        return SpydraFullConfig

    async def execute(self, inputs):
        config = self.config.config
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a Spydra API key")
        route = OPERATIONS[config.operation]
        values = config.model_dump(mode="json", exclude_none=True)
        params = {wire: (str(values[key]).lower() if isinstance(values[key], bool) else values[key])
                  for key, wire in route["query"] if key in values}
        body = {key: values[key] for key in route["body"] if key in values} if route["body"] else None
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(route["method"], credential.api_url + route["path"],
                    headers={"X-API-KEY": credential.api_key, "Accept": "application/json"},
                    params=params, **({"json": body} if body is not None else {}))
            if response.status_code not in route["statuses"]:
                message = "Spydra did not confirm the request; check your key, deployment and resource permissions."
                try:
                    failure = response.json()
                    if isinstance(failure, dict) and isinstance(failure.get("message"), str):
                        message = failure["message"].replace(credential.api_key, "[redacted]")[:2000]
                except ValueError:
                    pass
                return {"status": "error", "http_status": response.status_code,
                        "status_code": response.status_code, "error": message}
            if len(response.content) > 5_000_000:
                raise ValueError("Spydra response exceeds the JSON size limit")
            data = response.json()
            if not isinstance(data, dict) or "errorCode" in data or "error" in data:
                raise ValueError("Spydra returned an unexpected response")
            if config.operation.startswith("list_") and (
                    not isinstance(data.get("records"), list)
                    or any(not isinstance(row, dict) for row in data["records"])):
                raise ValueError("Spydra did not return a records page")
            if route["method"] != "GET" and not isinstance(data.get("receiptId"), str):
                raise ValueError("Spydra did not return a transaction receipt")
            # A successful transport does not mean an asynchronous write committed.
            return {"status": "success", "data": data, "http_status": response.status_code}
        except (httpx.HTTPError, SSRFError):
            return {"status": "error", "error": "Spydra request could not be completed; inspect the transaction before retrying a write."}
        except (ValueError, UnicodeError):
            return {"status": "error", "error": "Spydra returned an invalid JSON response; inspect the transaction before retrying a write."}
