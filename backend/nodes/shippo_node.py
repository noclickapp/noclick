"""Shippo shipping, tracking, carrier, and order workflow actions."""

from __future__ import annotations

import hashlib
import hmac
import json
import mimetypes
import re
import time
from typing import Annotated, Any, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Discriminator, Field, create_model

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.binary_output import BinaryOutput
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin, WebhookTriggerConfigBase


# Shippo operation metadata from the provider API reference.
# Kept in the node module so discovery needs no external catalog or shared list.
_catalog = {'source_url': 'https://docs.goshippo.com/spec/shippoapi/public-api.yaml',
 'source_sha256': '89a0aedb2b88d93adc8a12a465979770f9c057a7b1c43cf9b40055dd43dba8be',
 'operations': [{'name': 'add_shipments_to_batch',
                 'label': 'Add shipments to a batch',
                 'description': 'Adds batch shipments to an existing batch.',
                 'category': 'Batches',
                 'method': 'POST',
                 'path': '/batches/{BatchId}/add_shipments',
                 'path_params': ['BatchId'],
                 'required_query': [],
                 'body_type': 'application/json',
                 'body_required': True,
                 'body_required_fields': []},
                {'name': 'create_address',
                 'label': 'Create a new address',
                 'description': 'Creates a new address object. You can use address objects to '
                                'create new shipments, calculate rates, and to create orders.',
                 'category': 'Addresses',
                 'method': 'POST',
                 'path': '/addresses',
                 'path_params': [],
                 'required_query': [],
                 'body_type': 'application/json',
                 'body_required': True,
                 'body_required_fields': ['country']},
                {'name': 'create_batch',
                 'label': 'Create a batch',
                 'description': 'Creates a new batch object for purchasing shipping labels for '
                                'many shipments at once. Batches are created asynchronously. This '
                                "means that the API response won't include your batch shipments "
                                'yet. You need to retrieve the batch later to verify that all '
                                'batch shipments are valid.',
                 'category': 'Batches',
                 'method': 'POST',
                 'path': '/batches',
                 'path_params': [],
                 'required_query': [],
                 'body_type': 'application/json',
                 'body_required': True,
                 'body_required_fields': ['batch_shipments',
                                          'default_carrier_account',
                                          'default_servicelevel_token']},
                {'name': 'create_carrier_account',
                 'label': 'Create a new carrier account',
                 'description': 'Creates a new carrier account or connects an existing carrier '
                                'account to the Shippo account.',
                 'category': 'Carrier Accounts',
                 'method': 'POST',
                 'path': '/carrier_accounts',
                 'path_params': [],
                 'required_query': [],
                 'body_type': 'application/json',
                 'body_required': True,
                 'body_required_fields': ['account_id', 'carrier', 'parameters']},
                {'name': 'create_customs_declaration',
                 'label': 'Create a new customs declaration',
                 'description': 'Creates a new customs declaration object',
                 'category': 'Customs Declarations',
                 'method': 'POST',
                 'path': '/customs/declarations',
                 'path_params': [],
                 'required_query': [],
                 'body_type': 'application/json',
                 'body_required': True,
                 'body_required_fields': ['certify',
                                          'certify_signer',
                                          'contents_type',
                                          'items',
                                          'non_delivery_option']},
                {'name': 'create_customs_item',
                 'label': 'Create a new customs item',
                 'description': 'Creates a new customs item object.',
                 'category': 'Customs Items',
                 'method': 'POST',
                 'path': '/customs/items',
                 'path_params': [],
                 'required_query': [],
                 'body_type': 'application/json',
                 'body_required': True,
                 'body_required_fields': ['description',
                                          'mass_unit',
                                          'net_weight',
                                          'origin_country',
                                          'quantity',
                                          'value_amount',
                                          'value_currency']},
                {'name': 'create_embedded_authorization',
                 'label': 'Create a JWT',
                 'description': 'Creates a short-lived JSON Web Token (JWT) that client-side '
                                'applications can use',
                 'category': 'Embedded Authorization',
                 'method': 'POST',
                 'path': '/embedded/authz',
                 'path_params': [],
                 'required_query': [],
                 'body_type': 'application/json',
                 'body_required': True,
                 'body_required_fields': ['scope']},
                {'name': 'create_live_rate',
                 'label': 'Generate a live rates request',
                 'description': 'Initiates a live rates request. Include either the object ID for',
                 'category': 'Rates at Checkout',
                 'method': 'POST',
                 'path': '/live-rates',
                 'path_params': [],
                 'required_query': [],
                 'body_type': 'application/json',
                 'body_required': True,
                 'body_required_fields': ['address_to', 'line_items']},
                {'name': 'create_manifest',
                 'label': 'Create a new manifest',
                 'description': 'Creates a new manifest object.',
                 'category': 'Manifests',
                 'method': 'POST',
                 'path': '/manifests',
                 'path_params': [],
                 'required_query': [],
                 'body_type': 'application/json',
                 'body_required': True,
                 'body_required_fields': ['address_from', 'carrier_account', 'shipment_date']},
                {'name': 'create_order',
                 'label': 'Create a new order',
                 'description': 'Creates a new order object.',
                 'category': 'Orders',
                 'method': 'POST',
                 'path': '/orders',
                 'path_params': [],
                 'required_query': [],
                 'body_type': 'application/json',
                 'body_required': True,
                 'body_required_fields': ['placed_at', 'to_address']},
                {'name': 'create_parcel',
                 'label': 'Create a new parcel',
                 'description': 'Creates a new parcel object.',
                 'category': 'Parcels',
                 'method': 'POST',
                 'path': '/parcels',
                 'path_params': [],
                 'required_query': [],
                 'body_type': 'application/json',
                 'body_required': True,
                 'body_required_fields': []},
                {'name': 'create_pickup',
                 'label': 'Create a pickup',
                 'description': 'Creates a pickup object. This request is for a carrier to come to '
                                'a specified location to take a package for shipping.',
                 'category': 'Pickups',
                 'method': 'POST',
                 'path': '/pickups',
                 'path_params': [],
                 'required_query': [],
                 'body_type': 'application/json',
                 'body_required': True,
                 'body_required_fields': ['carrier_account',
                                          'location',
                                          'requested_end_time',
                                          'requested_start_time',
                                          'transactions']},
                {'name': 'create_refund',
                 'label': 'Create a refund',
                 'description': 'Creates a new refund object.',
                 'category': 'Refunds',
                 'method': 'POST',
                 'path': '/refunds',
                 'path_params': [],
                 'required_query': [],
                 'body_type': 'application/json',
                 'body_required': True,
                 'body_required_fields': ['transaction']},
                {'name': 'create_service_group',
                 'label': 'Create a new service group',
                 'description': 'Creates a new service group.',
                 'category': 'Service Groups',
                 'method': 'POST',
                 'path': '/service-groups',
                 'path_params': [],
                 'required_query': [],
                 'body_type': 'application/json',
                 'body_required': True,
                 'body_required_fields': ['description', 'name', 'service_levels', 'type']},
                {'name': 'create_shipment',
                 'label': 'Create a new shipment',
                 'description': 'Creates a new shipment object.',
                 'category': 'Shipments',
                 'method': 'POST',
                 'path': '/shipments',
                 'path_params': [],
                 'required_query': [],
                 'body_type': 'application/json',
                 'body_required': True,
                 'body_required_fields': ['address_from', 'address_to', 'parcels']},
                {'name': 'create_shippo_account',
                 'label': 'Create a Shippo Account',
                 'description': 'Creates a new [Shippo Managed '
                                'Account](https://docs.goshippo.com/docs/platformaccounts/platform_using_accounts/).',
                 'category': 'Shippo Accounts',
                 'method': 'POST',
                 'path': '/shippo-accounts',
                 'path_params': [],
                 'required_query': [],
                 'body_type': 'application/json',
                 'body_required': True,
                 'body_required_fields': ['company_name', 'email', 'first_name', 'last_name']},
                {'name': 'create_track',
                 'label': 'Register a tracking webhook',
                 'description': 'Registers a webhook that will send HTTP notifications to you when '
                                'the status of your tracked package changes. For more details on '
                                'creating a webhook, see our guides on '
                                '[Webhooks](https://docs.goshippo.com/docs/tracking/webhooks/) and '
                                '[Tracking](https://docs.goshippo.com/docs/tracking/tracking/).',
                 'category': 'Tracking Status',
                 'method': 'POST',
                 'path': '/tracks',
                 'path_params': [],
                 'required_query': [],
                 'body_type': 'application/json',
                 'body_required': True,
                 'body_required_fields': ['carrier', 'tracking_number']},
                {'name': 'create_transaction',
                 'label': 'Create a shipping label',
                 'description': 'Creates a new transaction object and purchases the shipping label '
                                'using a rate object that has previously been created.',
                 'category': 'Transactions',
                 'method': 'POST',
                 'path': '/transactions',
                 'path_params': [],
                 'required_query': [],
                 'body_type': 'application/json',
                 'body_required': True,
                 'body_required_fields': []},
                {'name': 'create_user_parcel_template',
                 'label': 'Create a new user parcel template',
                 'description': 'Creates a new user parcel template.',
                 'category': 'User Parcel Templates',
                 'method': 'POST',
                 'path': '/user-parcel-templates',
                 'path_params': [],
                 'required_query': [],
                 'body_type': 'application/json',
                 'body_required': True,
                 'body_required_fields': []},
                {'name': 'create_webhook',
                 'label': 'Create a new webhook',
                 'description': 'Creates a new webhook to send notifications to a URL when a '
                                'specific event occurs.',
                 'category': 'Webhooks',
                 'method': 'POST',
                 'path': '/webhooks',
                 'path_params': [],
                 'required_query': [],
                 'body_type': 'application/json',
                 'body_required': True,
                 'body_required_fields': ['event', 'url']},
                {'name': 'delete_default_parcel_template',
                 'label': 'Clear current default parcel template',
                 'description': 'Clears the currently configured default parcel template for live '
                                'rates.',
                 'category': 'Rates at Checkout',
                 'method': 'DELETE',
                 'path': '/live-rates/settings/parcel-template',
                 'path_params': [],
                 'required_query': [],
                 'body_type': 'none',
                 'body_required': False,
                 'body_required_fields': []},
                {'name': 'delete_service_group',
                 'label': 'Delete a service group',
                 'description': 'Deletes an existing service group using an object ID.',
                 'category': 'Service Groups',
                 'method': 'DELETE',
                 'path': '/service-groups/{ServiceGroupId}',
                 'path_params': ['ServiceGroupId'],
                 'required_query': [],
                 'body_type': 'none',
                 'body_required': False,
                 'body_required_fields': []},
                {'name': 'delete_user_parcel_template',
                 'label': 'Delete a user parcel template',
                 'description': 'Deletes a user parcel template using an object ID.',
                 'category': 'User Parcel Templates',
                 'method': 'DELETE',
                 'path': '/user-parcel-templates/{UserParcelTemplateObjectId}',
                 'path_params': ['UserParcelTemplateObjectId'],
                 'required_query': [],
                 'body_type': 'none',
                 'body_required': False,
                 'body_required_fields': []},
                {'name': 'delete_webhook',
                 'label': 'Delete a specific webhook',
                 'description': 'Deletes a specific webhook using the webhook object ID.',
                 'category': 'Webhooks',
                 'method': 'DELETE',
                 'path': '/webhooks/{webhookId}',
                 'path_params': ['webhookId'],
                 'required_query': [],
                 'body_type': 'none',
                 'body_required': False,
                 'body_required_fields': []},
                {'name': 'get_address',
                 'label': 'Retrieve an address',
                 'description': 'Returns an existing address using an object ID.',
                 'category': 'Addresses',
                 'method': 'GET',
                 'path': '/addresses/{AddressId}',
                 'path_params': ['AddressId'],
                 'required_query': [],
                 'body_type': 'none',
                 'body_required': False,
                 'body_required_fields': []},
                {'name': 'get_batch',
                 'label': 'Retrieve a batch',
                 'description': 'Returns a batch using an object ID.',
                 'category': 'Batches',
                 'method': 'GET',
                 'path': '/batches/{BatchId}',
                 'path_params': ['BatchId'],
                 'required_query': [],
                 'body_type': 'none',
                 'body_required': False,
                 'body_required_fields': []},
                {'name': 'get_carrier_account',
                 'label': 'Retrieve a carrier account',
                 'description': 'Returns an existing carrier account using an object ID.',
                 'category': 'Carrier Accounts',
                 'method': 'GET',
                 'path': '/carrier_accounts/{CarrierAccountId}',
                 'path_params': ['CarrierAccountId'],
                 'required_query': [],
                 'body_type': 'none',
                 'body_required': False,
                 'body_required_fields': []},
                {'name': 'get_carrier_parcel_template',
                 'label': 'Retrieve a carrier parcel templates',
                 'description': 'Fetches the parcel template information for a specific carrier '
                                'parcel template, identified by the token.',
                 'category': 'Carrier Parcel Templates',
                 'method': 'GET',
                 'path': '/parcel-templates/{CarrierParcelTemplateToken}',
                 'path_params': ['CarrierParcelTemplateToken'],
                 'required_query': [],
                 'body_type': 'none',
                 'body_required': False,
                 'body_required_fields': []},
                {'name': 'get_carrier_registration_status',
                 'label': 'Get Carrier Registration status',
                 'description': 'Returns the registration status for the given account for the '
                                'given carrier',
                 'category': 'Carrier Accounts',
                 'method': 'GET',
                 'path': '/carrier_accounts/reg-status',
                 'path_params': [],
                 'required_query': ['carrier'],
                 'body_type': 'none',
                 'body_required': False,
                 'body_required_fields': []},
                {'name': 'get_customs_declaration',
                 'label': 'Retrieve a customs declaration',
                 'description': 'Returns an existing customs declaration using an object ID',
                 'category': 'Customs Declarations',
                 'method': 'GET',
                 'path': '/customs/declarations/{CustomsDeclarationId}',
                 'path_params': ['CustomsDeclarationId'],
                 'required_query': [],
                 'body_type': 'none',
                 'body_required': False,
                 'body_required_fields': []},
                {'name': 'get_customs_item',
                 'label': 'Retrieve a customs item',
                 'description': 'Returns an existing customs item using an object ID',
                 'category': 'Customs Items',
                 'method': 'GET',
                 'path': '/customs/items/{CustomsItemId}',
                 'path_params': ['CustomsItemId'],
                 'required_query': [],
                 'body_type': 'none',
                 'body_required': False,
                 'body_required_fields': []},
                {'name': 'get_default_parcel_template',
                 'label': 'Show current default parcel template',
                 'description': 'Retrieve and display the currently configured default parcel '
                                'template for live rates.',
                 'category': 'Rates at Checkout',
                 'method': 'GET',
                 'path': '/live-rates/settings/parcel-template',
                 'path_params': [],
                 'required_query': [],
                 'body_type': 'none',
                 'body_required': False,
                 'body_required_fields': []},
                {'name': 'get_manifest',
                 'label': 'Retrieve a manifest',
                 'description': 'Returns an existing manifest using an object ID.',
                 'category': 'Manifests',
                 'method': 'GET',
                 'path': '/manifests/{ManifestId}',
                 'path_params': ['ManifestId'],
                 'required_query': [],
                 'body_type': 'none',
                 'body_required': False,
                 'body_required_fields': []},
                {'name': 'get_order',
                 'label': 'Retrieve an order',
                 'description': 'Retrieves an existing order using an object ID.',
                 'category': 'Orders',
                 'method': 'GET',
                 'path': '/orders/{OrderId}',
                 'path_params': ['OrderId'],
                 'required_query': [],
                 'body_type': 'none',
                 'body_required': False,
                 'body_required_fields': []},
                {'name': 'get_parcel',
                 'label': 'Retrieve an existing parcel',
                 'description': 'Returns parcel details using an existing parcel object ID (this '
                                'will not return parcel details associated with un-purchased '
                                'shipment/rate parcel object IDs).',
                 'category': 'Parcels',
                 'method': 'GET',
                 'path': '/parcels/{ParcelId}',
                 'path_params': ['ParcelId'],
                 'required_query': [],
                 'body_type': 'none',
                 'body_required': False,
                 'body_required_fields': []},
                {'name': 'get_rate',
                 'label': 'Retrieve a rate',
                 'description': 'Returns an existing rate using a rate object ID. Rates older than '
                                '390 days are not returned.',
                 'category': 'Rates',
                 'method': 'GET',
                 'path': '/rates/{RateId}',
                 'path_params': ['RateId'],
                 'required_query': [],
                 'body_type': 'none',
                 'body_required': False,
                 'body_required_fields': []},
                {'name': 'get_refund',
                 'label': 'Retrieve a refund',
                 'description': 'Returns an existing rate using a rate object ID.',
                 'category': 'Refunds',
                 'method': 'GET',
                 'path': '/refunds/{RefundId}',
                 'path_params': ['RefundId'],
                 'required_query': [],
                 'body_type': 'none',
                 'body_required': False,
                 'body_required_fields': []},
                {'name': 'get_shipment',
                 'label': 'Retrieve a shipment',
                 'description': 'Returns an existing shipment using an object ID. Shipment objects '
                                'older than 390 days are not returned.',
                 'category': 'Shipments',
                 'method': 'GET',
                 'path': '/shipments/{ShipmentId}',
                 'path_params': ['ShipmentId'],
                 'required_query': [],
                 'body_type': 'none',
                 'body_required': False,
                 'body_required_fields': []},
                {'name': 'get_shippo_account',
                 'label': 'Retrieve a Shippo Account',
                 'description': 'Returns a Shippo Managed Account using an object ID.',
                 'category': 'Shippo Accounts',
                 'method': 'GET',
                 'path': '/shippo-accounts/{ShippoAccountId}',
                 'path_params': ['ShippoAccountId'],
                 'required_query': [],
                 'body_type': 'none',
                 'body_required': False,
                 'body_required_fields': []},
                {'name': 'get_track',
                 'label': 'Get a tracking status',
                 'description': 'Returns the tracking status of a shipment using a carrier name '
                                'and a tracking number.',
                 'category': 'Tracking Status',
                 'method': 'GET',
                 'path': '/tracks/{Carrier}/{TrackingNumber}',
                 'path_params': ['Carrier', 'TrackingNumber'],
                 'required_query': [],
                 'body_type': 'none',
                 'body_required': False,
                 'body_required_fields': []},
                {'name': 'get_transaction',
                 'label': 'Retrieve a shipping label',
                 'description': 'Returns an existing transaction using an object ID.',
                 'category': 'Transactions',
                 'method': 'GET',
                 'path': '/transactions/{TransactionId}',
                 'path_params': ['TransactionId'],
                 'required_query': [],
                 'body_type': 'none',
                 'body_required': False,
                 'body_required_fields': []},
                {'name': 'get_user_parcel_template',
                 'label': 'Retrieves a user parcel template',
                 'description': 'Returns the parcel template information for a specific user '
                                'parcel',
                 'category': 'User Parcel Templates',
                 'method': 'GET',
                 'path': '/user-parcel-templates/{UserParcelTemplateObjectId}',
                 'path_params': ['UserParcelTemplateObjectId'],
                 'required_query': [],
                 'body_type': 'none',
                 'body_required': False,
                 'body_required_fields': []},
                {'name': 'get_webhook',
                 'label': 'Retrieve a specific webhook',
                 'description': 'Returns the details of a specific webhook using the webhook '
                                'object ID.',
                 'category': 'Webhooks',
                 'method': 'GET',
                 'path': '/webhooks/{webhookId}',
                 'path_params': ['webhookId'],
                 'required_query': [],
                 'body_type': 'none',
                 'body_required': False,
                 'body_required_fields': []},
                {'name': 'initiate_oauth2_signin',
                 'label': 'Connect an existing carrier account using OAuth 2.0',
                 'description': 'Used by client applications to setup or reconnect an existing '
                                'carrier account with carriers that support OAuth 2.0',
                 'category': 'Carrier Accounts',
                 'method': 'GET',
                 'path': '/carrier_accounts/{CarrierAccountObjectId}/signin/initiate',
                 'path_params': ['CarrierAccountObjectId'],
                 'required_query': ['redirect_uri'],
                 'body_type': 'none',
                 'body_required': False,
                 'body_required_fields': []},
                {'name': 'list_addresses',
                 'label': 'List all addresses',
                 'description': 'Returns a list of all address objects that have been created in '
                                'this account.',
                 'category': 'Addresses',
                 'method': 'GET',
                 'path': '/addresses',
                 'path_params': [],
                 'required_query': [],
                 'body_type': 'none',
                 'body_required': False,
                 'body_required_fields': []},
                {'name': 'list_carrier_accounts',
                 'label': 'List all carrier accounts',
                 'description': 'Returns a list of all carrier accounts connected to your Shippo '
                                'account. These carrier accounts include both Shippo carrier '
                                'accounts and your own carrier accounts that you have connected to '
                                'your Shippo account.',
                 'category': 'Carrier Accounts',
                 'method': 'GET',
                 'path': '/carrier_accounts',
                 'path_params': [],
                 'required_query': [],
                 'body_type': 'none',
                 'body_required': False,
                 'body_required_fields': []},
                {'name': 'list_carrier_parcel_templates',
                 'label': 'List all carrier parcel templates',
                 'description': 'List all carrier parcel template objects.',
                 'category': 'Carrier Parcel Templates',
                 'method': 'GET',
                 'path': '/parcel-templates',
                 'path_params': [],
                 'required_query': [],
                 'body_type': 'none',
                 'body_required': False,
                 'body_required_fields': []},
                {'name': 'list_customs_declarations',
                 'label': 'List all customs declarations',
                 'description': 'Returns a list of all customs declaration objects',
                 'category': 'Customs Declarations',
                 'method': 'GET',
                 'path': '/customs/declarations',
                 'path_params': [],
                 'required_query': [],
                 'body_type': 'none',
                 'body_required': False,
                 'body_required_fields': []},
                {'name': 'list_customs_items',
                 'label': 'List all customs items',
                 'description': 'Returns a list all customs items objects.',
                 'category': 'Customs Items',
                 'method': 'GET',
                 'path': '/customs/items',
                 'path_params': [],
                 'required_query': [],
                 'body_type': 'none',
                 'body_required': False,
                 'body_required_fields': []},
                {'name': 'list_manifests',
                 'label': 'List all manifests',
                 'description': 'Returns a list of all manifest objects.',
                 'category': 'Manifests',
                 'method': 'GET',
                 'path': '/manifests',
                 'path_params': [],
                 'required_query': [],
                 'body_type': 'none',
                 'body_required': False,
                 'body_required_fields': []},
                {'name': 'list_orders',
                 'label': 'List all orders',
                 'description': 'Returns a list of all order objects.',
                 'category': 'Orders',
                 'method': 'GET',
                 'path': '/orders',
                 'path_params': [],
                 'required_query': [],
                 'body_type': 'none',
                 'body_required': False,
                 'body_required_fields': []},
                {'name': 'list_parcels',
                 'label': 'List all parcels',
                 'description': 'Returns a list of all parcel objects.',
                 'category': 'Parcels',
                 'method': 'GET',
                 'path': '/parcels',
                 'path_params': [],
                 'required_query': [],
                 'body_type': 'none',
                 'body_required': False,
                 'body_required_fields': []},
                {'name': 'list_refunds',
                 'label': 'List all refunds',
                 'description': 'Returns a list all refund objects.',
                 'category': 'Refunds',
                 'method': 'GET',
                 'path': '/refunds/',
                 'path_params': [],
                 'required_query': [],
                 'body_type': 'none',
                 'body_required': False,
                 'body_required_fields': []},
                {'name': 'list_service_groups',
                 'label': 'List all service groups',
                 'description': 'Returns a list of service group objects.',
                 'category': 'Service Groups',
                 'method': 'GET',
                 'path': '/service-groups',
                 'path_params': [],
                 'required_query': [],
                 'body_type': 'none',
                 'body_required': False,
                 'body_required_fields': []},
                {'name': 'list_shipment_rates',
                 'label': 'Retrieve shipment rates',
                 'description': 'Returns a paginated list of rates associated with a shipment. '
                                'Rates for shipments older than 390 days are not returned.',
                 'category': 'Rates',
                 'method': 'GET',
                 'path': '/shipments/{ShipmentId}/rates',
                 'path_params': ['ShipmentId'],
                 'required_query': [],
                 'body_type': 'none',
                 'body_required': False,
                 'body_required_fields': []},
                {'name': 'list_shipment_rates_by_currency_code',
                 'label': 'Retrieve shipment rates in currency',
                 'description': 'Returns all available shipping rates for a shipment object.',
                 'category': 'Rates',
                 'method': 'GET',
                 'path': '/shipments/{ShipmentId}/rates/{CurrencyCode}',
                 'path_params': ['ShipmentId', 'CurrencyCode'],
                 'required_query': [],
                 'body_type': 'none',
                 'body_required': False,
                 'body_required_fields': []},
                {'name': 'list_shipments',
                 'label': 'List all shipments',
                 'description': 'Returns a list of all shipment objects.',
                 'category': 'Shipments',
                 'method': 'GET',
                 'path': '/shipments',
                 'path_params': [],
                 'required_query': [],
                 'body_type': 'none',
                 'body_required': False,
                 'body_required_fields': []},
                {'name': 'list_shippo_accounts',
                 'label': 'List all Shippo Accounts',
                 'description': 'Returns a list of Shippo Managed Accounts objects.',
                 'category': 'Shippo Accounts',
                 'method': 'GET',
                 'path': '/shippo-accounts',
                 'path_params': [],
                 'required_query': [],
                 'body_type': 'none',
                 'body_required': False,
                 'body_required_fields': []},
                {'name': 'list_transactions',
                 'label': 'List all shipping labels',
                 'description': 'Returns a list of all transaction objects.',
                 'category': 'Transactions',
                 'method': 'GET',
                 'path': '/transactions',
                 'path_params': [],
                 'required_query': [],
                 'body_type': 'none',
                 'body_required': False,
                 'body_required_fields': []},
                {'name': 'list_user_parcel_templates',
                 'label': 'List all user parcel templates',
                 'description': 'Returns a list all of all user parcel template objects.',
                 'category': 'User Parcel Templates',
                 'method': 'GET',
                 'path': '/user-parcel-templates',
                 'path_params': [],
                 'required_query': [],
                 'body_type': 'none',
                 'body_required': False,
                 'body_required_fields': []},
                {'name': 'list_webhooks',
                 'label': 'List all webhooks',
                 'description': 'Returns a list of all webhooks you have created.',
                 'category': 'Webhooks',
                 'method': 'GET',
                 'path': '/webhooks',
                 'path_params': [],
                 'required_query': [],
                 'body_type': 'none',
                 'body_required': False,
                 'body_required_fields': []},
                {'name': 'purchase_batch',
                 'label': 'Purchase a batch',
                 'description': 'Purchases an existing batch with a status of `VALID`. ',
                 'category': 'Batches',
                 'method': 'POST',
                 'path': '/batches/{BatchId}/purchase',
                 'path_params': ['BatchId'],
                 'required_query': [],
                 'body_type': 'none',
                 'body_required': False,
                 'body_required_fields': []},
                {'name': 'register_carrier_account',
                 'label': 'Add a Shippo carrier account',
                 'description': 'Adds a Shippo carrier account',
                 'category': 'Carrier Accounts',
                 'method': 'POST',
                 'path': '/carrier_accounts/register/new',
                 'path_params': [],
                 'required_query': [],
                 'body_type': 'application/json',
                 'body_required': True,
                 'body_required_fields': []},
                {'name': 'remove_shipments_from_batch',
                 'label': 'Remove shipments from a batch',
                 'description': 'Removes shipments from an existing batch shipment.',
                 'category': 'Batches',
                 'method': 'POST',
                 'path': '/batches/{BatchId}/remove_shipments',
                 'path_params': ['BatchId'],
                 'required_query': [],
                 'body_type': 'application/json',
                 'body_required': True,
                 'body_required_fields': []},
                {'name': 'update_carrier_account',
                 'label': 'Update a carrier account',
                 'description': 'Updates an existing carrier account object. The account_id and '
                                "carrier can't be updated. This is because they form the unique "
                                'identifier together.',
                 'category': 'Carrier Accounts',
                 'method': 'PUT',
                 'path': '/carrier_accounts/{CarrierAccountId}',
                 'path_params': ['CarrierAccountId'],
                 'required_query': [],
                 'body_type': 'application/json',
                 'body_required': False,
                 'body_required_fields': ['account_id', 'carrier']},
                {'name': 'update_default_parcel_template',
                 'label': 'Update default parcel template',
                 'description': 'Update the currently configured default parcel template for live '
                                'rates. The object_id in the request payload should identify the '
                                'user parcel template to be the new default.',
                 'category': 'Rates at Checkout',
                 'method': 'PUT',
                 'path': '/live-rates/settings/parcel-template',
                 'path_params': [],
                 'required_query': [],
                 'body_type': 'application/json',
                 'body_required': False,
                 'body_required_fields': []},
                {'name': 'update_service_group',
                 'label': 'Update an existing service group',
                 'description': 'Updates an existing service group object. The object_id cannot be '
                                'updated as it is the unique identifier for the object.',
                 'category': 'Service Groups',
                 'method': 'PUT',
                 'path': '/service-groups',
                 'path_params': [],
                 'required_query': [],
                 'body_type': 'application/json',
                 'body_required': False,
                 'body_required_fields': ['description',
                                          'is_active',
                                          'name',
                                          'object_id',
                                          'service_levels',
                                          'type']},
                {'name': 'update_shippo_account',
                 'label': 'Update a Shippo Account',
                 'description': 'Updates a Shippo Managed Account using an object ID.',
                 'category': 'Shippo Accounts',
                 'method': 'PUT',
                 'path': '/shippo-accounts/{ShippoAccountId}',
                 'path_params': ['ShippoAccountId'],
                 'required_query': [],
                 'body_type': 'application/json',
                 'body_required': False,
                 'body_required_fields': ['company_name', 'email', 'first_name', 'last_name']},
                {'name': 'update_user_parcel_template',
                 'label': 'Update an existing user parcel template',
                 'description': 'Updates an existing user parcel template.',
                 'category': 'User Parcel Templates',
                 'method': 'PUT',
                 'path': '/user-parcel-templates/{UserParcelTemplateObjectId}',
                 'path_params': ['UserParcelTemplateObjectId'],
                 'required_query': [],
                 'body_type': 'application/json',
                 'body_required': False,
                 'body_required_fields': ['distance_unit', 'height', 'length', 'name', 'width']},
                {'name': 'update_webhook',
                 'label': 'Update an existing webhook',
                 'description': 'Updates an existing webhook using the webhook object ID.',
                 'category': 'Webhooks',
                 'method': 'PUT',
                 'path': '/webhooks/{webhookId}',
                 'path_params': ['webhookId'],
                 'required_query': [],
                 'body_type': 'application/json',
                 'body_required': True,
                 'body_required_fields': ['event', 'url']},
                {'name': 'validate_address',
                 'label': 'Validate an address',
                 'description': 'Validates an existing address using an object ID',
                 'category': 'Addresses',
                 'method': 'GET',
                 'path': '/addresses/{AddressId}/validate',
                 'path_params': ['AddressId'],
                 'required_query': [],
                 'body_type': 'none',
                 'body_required': False,
                 'body_required_fields': []}]}
OPERATIONS: dict[str, dict[str, Any]] = {op["name"]: op for op in _catalog["operations"]}
assert len(OPERATIONS) == len(_catalog["operations"]), "Duplicate Shippo operation"
_JSON_EDITOR = {"ui:widget": "code_editor", "x-code-language": "json"}
_BASE_URL = "https://api.goshippo.com"
_API_VERSION = "2018-02-08"


class ShippoApiKeyCredential(BaseModel):
    """Shippo test or live API token."""

    credential_type: Literal["shippo_api_key"] = Field(
        "shippo_api_key", json_schema_extra={"ui:hidden": True}
    )
    api_key: str = Field(
        ..., title="Shippo API Token",
        description="Paste a test token (shippo_test_) to try workflows without live label charges, or a live token (shippo_live_) for production.",
        json_schema_extra={"ui:widget": "password"},
    )

    model_config = ConfigDict(title="Shippo API Token", json_schema_extra={
        "x-credential-url": "https://apps.goshippo.com/",
        "x-credential-instructions": (
            "Create or sign in to a Shippo account, open API Configuration > Developer keys, "
            "then copy a Test token for development or a Live token for production."
        ),
    })


def _field_name(prefix: str, raw: str) -> str:
    return prefix + "_" + re.sub(r"[^a-zA-Z0-9]+", "_", raw).strip("_").lower()


def _make_config(op: dict[str, Any]) -> type[BaseModel]:
    name = op["name"]
    fields: dict[str, tuple[Any, Any]] = {
        "operation": (Literal[name], Field(
            name, title=op["label"], description=op["description"],
            json_schema_extra={
                "const": name, "ui:hidden": True,
                "x-category": op["category"], "x-display-name": op["label"],
                "x-is-trigger": False,
            },
        )),
    }
    for raw in op["path_params"]:
        fields[_field_name("path", raw)] = (
            str, Field(..., title=re.sub(r"(?<!^)(?=[A-Z])", " ", raw).title()),
        )
    for raw in op["required_query"]:
        fields[_field_name("query", raw)] = (str, Field(..., title=raw.replace("_", " ").title()))
    fields["query_json"] = (
        Optional[str], Field(None, title="Other Query Parameters (JSON)",
                             description="Optional filters and pagination from the Shippo API reference.",
                             json_schema_extra=_JSON_EDITOR),
    )
    if op["body_type"] == "application/json":
        description = "JSON request body from the Shippo API reference."
        if op["body_required_fields"]:
            description += " Required keys: " + ", ".join(op["body_required_fields"]) + "."
        required = op["body_required"] or bool(op["body_required_fields"])
        fields["body_json"] = (
            str if required else Optional[str],
            Field(... if required else None, title="Request Body (JSON)",
                  description=description, json_schema_extra=_JSON_EDITOR),
        )
    return create_model(
        "Shippo" + "".join(word.title() for word in name.split("_")) + "Config",
        __module__=__name__, **fields,
    )


CONFIG_MODELS = {name: _make_config(op) for name, op in OPERATIONS.items()}
globals().update({model.__name__: model for model in CONFIG_MODELS.values()})
# https://docs.goshippo.com/tracking/webhooks and WebhookPayload in the OpenAPI.
TRIGGER_EVENTS = {
    "on_tracking_updated": ("track_updated", "On Tracking Updated"),
    "on_transaction_created": ("transaction_created", "On Shipping Label Created"),
    "on_transaction_updated": ("transaction_updated", "On Shipping Label Updated"),
    "on_batch_created": ("batch_created", "On Batch Created"),
    "on_batch_purchased": ("batch_purchased", "On Batch Purchased"),
}


class ShippoWebhookConfig(WebhookTriggerConfigBase):
    is_test: bool = Field(False, title="Test Mode", description="Receive test events instead of live events.")
    hmac_secret: Optional[str] = Field(
        None, title="Webhook HMAC Secret",
        description="If Shippo has enabled HMAC for your account, paste the secret supplied by its solutions team. Otherwise leave empty; Shippo does not sign deliveries by default.",
        json_schema_extra={"ui:widget": "password"},
    )
    webhook_url: Optional[str] = Field(
        None, title="Webhook URL", description="Registered with Shippo automatically.",
        json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True},
    )


TRIGGER_MODELS = {
    name: create_model(
        "Shippo" + "".join(word.title() for word in name.split("_")) + "Config",
        __base__=ShippoWebhookConfig, __module__=__name__,
        operation=(Literal[name], Field(name, title=label, json_schema_extra={
            "const": name, "ui:hidden": True, "x-category": "Triggers",
            "x-is-trigger": True, "x-display-name": label,
        })),
    )
    for name, (_, label) in TRIGGER_EVENTS.items()
}
globals().update({model.__name__: model for model in TRIGGER_MODELS.values()})
ShippoConfig = Annotated[Union[tuple(CONFIG_MODELS.values()) + tuple(TRIGGER_MODELS.values())], Discriminator("operation")]


class ShippoNodeConfig(NodeConfig[ShippoConfig, ShippoApiKeyCredential]):
    model_config = ConfigDict(json_schema_extra={"x-agent-tool-provider": True})


def _parse_json(raw: Optional[str], label: str) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must contain valid JSON") from exc


class ShippoNode(ExternalWebhookTriggerMixin, WorkflowNode):
    """Run one of Shippo's shipping and tracking API actions."""

    integration_type = "automation-shippo"
    # Shippo enables HMAC separately through its solutions team, not registration.
    webhook_signing_secret_not_issued = True

    connection_evidence = ConnectionEvidence(operation="list_addresses", noun="addresses")
    edit_examples = [
        "List Shippo addresses", "Create a shipment and compare rates",
        "Buy a test shipping label", "Get tracking status for a package",
    ]

    @classmethod
    def get_config_model(cls):
        return ShippoNodeConfig

    @classmethod
    def registration_fingerprint_fields(cls, config):
        return {"is_test": bool(config.get("is_test", False))}

    @classmethod
    async def _register_external_webhook(cls, *, webhook_url, credential, config, node_id):
        operation = config.get("operation")
        if operation not in TRIGGER_EVENTS:
            raise ValueError("Choose a Shippo trigger")
        if not credential.get("api_key"):
            raise ValueError("Connect Shippo before activating this trigger")
        result = await cls._request(credential["api_key"], "create_webhook", {
            "body_json": json.dumps({"event": TRIGGER_EVENTS[operation][0], "url": webhook_url,
                                      "active": True, "is_test": bool(config.get("is_test", False))}),
        })
        external_id = result["data"].get("object_id")
        if not external_id:
            raise ValueError("Shippo did not return a webhook ID")
        return {"external_webhook_id": str(external_id)}

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id):
        external_id = config.get("external_webhook_id")
        if not external_id or not credential or not credential.get("api_key"):
            return
        await cls._request(credential["api_key"], "delete_webhook", {"path_webhookid": str(external_id)})

    @classmethod
    def verify_webhook_signature(cls, body: bytes, headers: dict[str, str], config: dict[str, Any]) -> bool:
        # https://docs.goshippo.com/tracking/webhook-security
        secret = config.get("hmac_secret")
        if not secret:
            return True
        header = next((v for k, v in headers.items() if k.lower() == "shippo-auth-signature"), "")
        parts = [part.strip() for part in header.split(",")]
        timestamp = next((p[2:] for p in parts if p.startswith("t=")), "")
        if not timestamp.isdigit():
            return False
        expected = hmac.new(str(secret).encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
        return any(hmac.compare_digest(p[3:], expected) for p in parts if p.startswith("v1="))

    @classmethod
    def filter_trigger_payload(cls, payload, config):
        event = TRIGGER_EVENTS.get(config.get("operation"))
        return bool(event and payload.get("event") == event[0]
                    and payload.get("test") == bool(config.get("is_test", False)))

    @classmethod
    def resolve_trigger_payload(cls, payload, config):
        return {"status": "success", "operation": config.get("operation"), "data": payload}

    @classmethod
    def resolve_agent_event(cls, output):
        if not isinstance(output, dict):
            return None
        wrapper = output.get("data") if "status" in output else output
        if not isinstance(wrapper, dict) or wrapper.get("event") not in {v[0] for v in TRIGGER_EVENTS.values()}:
            return super().resolve_agent_event(output)
        event = wrapper["event"]
        data = wrapper.get("data")
        if event.startswith("batch_"):
            # Shippo delivers a string, not a nested Batch object.
            content = str(data or "")
            match = re.fullmatch(r"batch (\S+) (?:created|processing complete)", content)
            batch_id = match.group(1) if match else None
            text = f"Shippo {event.replace('_', ' ')}: {content}"
            if batch_id:
                text += f"\nTo act: get_batch path_batchid={batch_id}"
            return {"text": text, "conversation_key": batch_id or content, "title": event.replace("_", " ").title()}
        if not isinstance(data, dict):
            return None
        if event == "track_updated":
            carrier = data.get("carrier") or ""
            tracking_number = data.get("tracking_number") or ""
            status = data.get("tracking_status") or {}
            if not isinstance(status, dict):
                status = {}
            location = status.get("location") or {}
            if not isinstance(location, dict):
                location = {}
            text = f"Shippo tracking updated: {carrier} {tracking_number} — {status.get('status') or 'status update'}"
            for label, value in (("Details", status.get("status_details")), ("At", status.get("status_date")),
                                 ("Location", ", ".join(str(location[k]) for k in ("city", "state", "country") if location.get(k))),
                                 ("Order", data.get("metadata")), ("Transaction", data.get("transaction"))):
                if value:
                    text += f"\n{label}: {value}"
            text += f"\nTo act: get_track path_carrier={carrier} path_trackingnumber={tracking_number}"
            key = f"{carrier}:{tracking_number}"
        else:
            transaction_id = data.get("object_id") or ""
            creator = data.get("created_by") or {}
            if not isinstance(creator, dict):
                creator = {}
            text = f"Shippo {event.replace('_', ' ')}: {transaction_id} — {data.get('status') or 'status update'}"
            for label, value in (("By", creator.get("username") or data.get("object_owner")),
                                 ("Tracking number", data.get("tracking_number")), ("Label", data.get("label_url")),
                                 ("Tracking URL", data.get("tracking_url_provider")), ("At", data.get("object_updated"))):
                if value:
                    text += f"\n{label}: {value}"
            text += f"\nTo act: get_transaction path_transactionid={transaction_id}"
            key = str(transaction_id)
        return {"text": text, "conversation_key": key, "title": event.replace("_", " ").title()}

    @staticmethod
    async def _request(token: str, name: str, values: dict[str, Any]) -> dict[str, Any]:
        op = OPERATIONS[name]
        path = op["path"]
        for raw in op["path_params"]:
            value = values.pop(_field_name("path", raw), None)
            if value is None or str(value).strip() in {"", ".", ".."}:
                raise ValueError(f"{raw} is required")
            path = path.replace("{" + raw + "}", quote(str(value), safe=""))
        params = _parse_json(values.pop("query_json", None), "Query Parameters") or {}
        if not isinstance(params, dict):
            raise ValueError("Query Parameters must be a JSON object")
        for raw in op["required_query"]:
            params[raw] = values.pop(_field_name("query", raw))
        headers = {
            "Authorization": f"ShippoToken {token}", "Accept": "application/json",
            "SHIPPO-API-VERSION": _API_VERSION,
        }
        kwargs: dict[str, Any] = {}
        body: Any = None
        if op["body_type"] == "application/json":
            body = _parse_json(values.pop("body_json", None), "Request Body")
            if op["body_required"] and body is None:
                raise ValueError("Request Body is required")
            missing = [key for key in op["body_required_fields"]
                       if not isinstance(body, dict) or key not in body]
            if missing:
                raise ValueError("Request Body is missing required keys: " + ", ".join(missing))
            if body is not None:
                kwargs["json"] = body
        started = time.monotonic()
        async with httpx.AsyncClient(timeout=60, follow_redirects=False) as client:
            response = await client.request(op["method"], _BASE_URL + path,
                                            params=params or None, headers=headers, **kwargs)
        if not response.content:
            data: Any = {}
        elif response.headers.get("content-type", "").startswith("application/json"):
            data = response.json()
        else:
            try:
                data = response.json()
            except ValueError:
                content_type = response.headers.get(
                    "content-type", "application/octet-stream"
                ).split(";", 1)[0].strip()
                extension = mimetypes.guess_extension(content_type) or ".bin"
                data = BinaryOutput(
                    data=response.content, content_type=content_type,
                    filename=f"shippo-{name}{extension}",
                )
        oauth_redirect = name == "initiate_oauth2_signin" and response.status_code == 302
        if response.is_error or (response.is_redirect and not oauth_redirect):
            detail = (data.get("detail") or data.get("message") or data.get("error")) if isinstance(data, dict) else None
            raise ValueError(f"Shippo API error {response.status_code}: {detail or 'request failed'}")
        if name == "create_transaction" and isinstance(data, dict):
            sync_label_missing = (
                isinstance(body, dict) and body.get("async") is False
                and not data.get("label_url")
            )
            if data.get("status") in {"ERROR", "FAILED"} or sync_label_missing:
                messages = data.get("messages") or []
                detail = "; ".join(
                    str(message.get("text") or message.get("message") or message)
                    if isinstance(message, dict) else str(message)
                    for message in messages
                )
                raise ValueError(f"Shippo label was not created: {detail or 'no label URL returned'}")
        next_page = response.links.get("next", {}).get("url")
        if not next_page and isinstance(data, dict):
            next_page = data.get("next") or (data.get("page_info") or {}).get("next")
        return {
            "status": "success", "operation": name, "status_code": response.status_code,
            "data": data, "next_page": next_page,
            **({"redirect_url": response.headers.get("location")} if oauth_redirect else {}),
            "total_count": data.get("count") if isinstance(data, dict) else None,
            "timing_ms": {"api_request": round((time.monotonic() - started) * 1000, 2)},
        }

    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        if isinstance(self.config, ShippoNodeConfig) and isinstance(self.config.config, ShippoWebhookConfig):
            return self.no_event_output(self.config.config.operation)
        if not isinstance(self.config, ShippoNodeConfig) or not self.config.credentials:
            raise ValueError("Connect a Shippo account before running this action")
        config = self.config.config
        return await self._request(
            self.config.credentials.api_key, config.operation,
            config.model_dump(exclude_none=True),
        )
