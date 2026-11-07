"""Paddle Billing REST API actions from Paddle's pinned OpenAPI 3.1 spec.

Paddle documents server-side API keys, not a third-party OAuth authorization
flow. Credentials are scoped to either the sandbox or live API host.
"""

from __future__ import annotations

import json
import re
import time
from typing import Annotated, Any, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Discriminator, Field, create_model

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence


API_HOSTS = {
    "sandbox": "https://sandbox-api.paddle.com",
    "live": "https://api.paddle.com",
}
_catalog = json.loads(r'''
{
  "source": "https://raw.githubusercontent.com/PaddleHQ/paddle-openapi/540ea17369325ff866b65ecf6c5105592f16fb5d/v1/openapi.yaml",
  "operations": [
    {
      "name": "list_addresses",
      "label": "List addresses for a customer",
      "category": "Addresses",
      "description": "Returns a paginated list of addresses for a customer. Use the query parameters to page through results. By default, Paddle returns addresses that are `active`. Use the `status` query parameter to return addresses that are archived.",
      "method": "GET",
      "path": "/customers/{customer_id}/addresses",
      "path_params": [
        {
          "name": "customer_id",
          "required": true,
          "description": "Paddle ID of the customer entity to work with."
        }
      ],
      "query_params": [
        {
          "name": "id",
          "required": false,
          "description": "Return only the IDs specified. Use a comma-separated list to get multiple entities."
        },
        {
          "name": "after",
          "required": false,
          "description": "Return entities after the specified Paddle ID when working with paginated endpoints. Used in the `meta.pagination.next` URL in responses for list operations."
        },
        {
          "name": "per_page",
          "required": false,
          "description": "Set how many entities are returned per page. Paddle returns the maximum number of results if a number greater than the maximum is requested. Check `meta.pagination.per_page` in the response to see how many were returned. Default: `50`; Maximum: `200`."
        },
        {
          "name": "order_by",
          "required": false,
          "description": "Order returned entities by the specified field and direction (`[ASC]` or `[DESC]`). For example, `?order_by=id[ASC]`. Valid fields for ordering: `id`."
        },
        {
          "name": "status",
          "required": false,
          "description": "Return entities that match the specified status. Use a comma-separated list to specify multiple status values."
        },
        {
          "name": "search",
          "required": false,
          "description": "Return entities that match a search query. Searches all fields except `status`, `created_at`, and `updated_at`."
        }
      ],
      "header_params": [
        {
          "name": "Skip-Count",
          "required": false,
          "description": "Set to `true` to skip the count query on list operations. When set, `meta.pagination.estimated_total` returns `-1` instead of an exact count."
        }
      ],
      "body_supported": false,
      "body_required": false,
      "body_required_keys": [],
      "permissions": [
        "address.read"
      ],
      "docs_url": "https://developer.paddle.com/api-reference/addresses/list-addresses"
    },
    {
      "name": "create_address",
      "label": "Create an address for a customer",
      "category": "Addresses",
      "description": "Creates a new address for a customer. For tax calculation, fraud prevention, and compliance purposes, you must include a `postal_code` when creating addresses for some countries. For example, ZIP codes in the USA and postcodes in the UK. See: [Supported countries](https://developer.paddle.com/concep",
      "method": "POST",
      "path": "/customers/{customer_id}/addresses",
      "path_params": [
        {
          "name": "customer_id",
          "required": true,
          "description": "Paddle ID of the customer entity to work with."
        }
      ],
      "query_params": [],
      "header_params": [],
      "body_supported": true,
      "body_required": true,
      "body_required_keys": [
        "country_code"
      ],
      "permissions": [
        "address.write"
      ],
      "docs_url": "https://developer.paddle.com/api-reference/addresses/create-address"
    },
    {
      "name": "get_address",
      "label": "Get an address for a customer",
      "category": "Addresses",
      "description": "Returns an address for a customer using its ID and related customer ID.",
      "method": "GET",
      "path": "/customers/{customer_id}/addresses/{address_id}",
      "path_params": [
        {
          "name": "address_id",
          "required": true,
          "description": "Paddle ID of the address entity to work with."
        },
        {
          "name": "customer_id",
          "required": true,
          "description": "Paddle ID of the customer entity to work with."
        }
      ],
      "query_params": [],
      "header_params": [],
      "body_supported": false,
      "body_required": false,
      "body_required_keys": [],
      "permissions": [
        "address.read"
      ],
      "docs_url": "https://developer.paddle.com/api-reference/addresses/get-address"
    },
    {
      "name": "update_address",
      "label": "Update an address for a customer",
      "category": "Addresses",
      "description": "Updates an address for a customer using its ID and related customer ID. If successful, your response includes a copy of the updated address entity.",
      "method": "PATCH",
      "path": "/customers/{customer_id}/addresses/{address_id}",
      "path_params": [
        {
          "name": "address_id",
          "required": true,
          "description": "Paddle ID of the address entity to work with."
        },
        {
          "name": "customer_id",
          "required": true,
          "description": "Paddle ID of the customer entity to work with."
        }
      ],
      "query_params": [],
      "header_params": [],
      "body_supported": true,
      "body_required": true,
      "body_required_keys": [],
      "permissions": [
        "address.write"
      ],
      "docs_url": "https://developer.paddle.com/api-reference/addresses/update-adddress"
    },
    {
      "name": "list_adjustments",
      "label": "List adjustments",
      "category": "Adjustments",
      "description": "Returns a paginated list of adjustments. Use the query parameters to page through results.",
      "method": "GET",
      "path": "/adjustments",
      "path_params": [],
      "query_params": [
        {
          "name": "id",
          "required": false,
          "description": "Return only the IDs specified. Use a comma-separated list to get multiple entities."
        },
        {
          "name": "after",
          "required": false,
          "description": "Return entities after the specified Paddle ID when working with paginated endpoints. Used in the `meta.pagination.next` URL in responses for list operations."
        },
        {
          "name": "action",
          "required": false,
          "description": "Return entities for the specified action. Use a comma-separated list to specify multiple action values."
        },
        {
          "name": "customer_id",
          "required": false,
          "description": "Return entities related to the specified customer. Use a comma-separated list to specify multiple customer IDs."
        },
        {
          "name": "order_by",
          "required": false,
          "description": "Order returned entities by the specified field and direction (`[ASC]` or `[DESC]`). For example, `?order_by=id[ASC]`. Valid fields for ordering: `id`."
        },
        {
          "name": "per_page",
          "required": false,
          "description": "Set how many entities are returned per page. Paddle returns the maximum number of results if a number greater than the maximum is requested. Check `meta.pagination.per_page` in the response to see how many were returned. Default: `10`; Maximum: `50`."
        },
        {
          "name": "status",
          "required": false,
          "description": "Return entities that match the specified status. Use a comma-separated list to specify multiple status values."
        },
        {
          "name": "subscription_id",
          "required": false,
          "description": "Return entities related to the specified subscription. Use a comma-separated list to specify multiple subscription IDs."
        },
        {
          "name": "transaction_id",
          "required": false,
          "description": "Return entities related to the specified transaction. Use a comma-separated list to specify multiple transaction IDs."
        }
      ],
      "header_params": [
        {
          "name": "Skip-Count",
          "required": false,
          "description": "Set to `true` to skip the count query on list operations. When set, `meta.pagination.estimated_total` returns `-1` instead of an exact count."
        }
      ],
      "body_supported": false,
      "body_required": false,
      "body_required_keys": [],
      "permissions": [
        "adjustment.read"
      ],
      "docs_url": "https://developer.paddle.com/api-reference/adjustments/list-adjustments"
    },
    {
      "name": "create_adjustment",
      "label": "Create an adjustment",
      "category": "Adjustments",
      "description": "Creates an adjustment for one or more transaction items. You can create adjustments to refund or credit all or part of a transaction and its items: * Refunds return an amount to a customer's original payment method. You can create refund adjustments for transactions that are `completed`. * Credits r",
      "method": "POST",
      "path": "/adjustments",
      "path_params": [],
      "query_params": [],
      "header_params": [],
      "body_supported": true,
      "body_required": true,
      "body_required_keys": [
        "action",
        "reason",
        "transaction_id"
      ],
      "permissions": [
        "adjustment.write"
      ],
      "docs_url": "https://developer.paddle.com/api-reference/adjustments/create-adjustment"
    },
    {
      "name": "get_adjustment_credit_note",
      "label": "Get a PDF credit note for an adjustment",
      "category": "Adjustments",
      "description": "Returns a link to a credit note PDF for an adjustment. Credit note PDFs are created for refunds and credits as a record of an adjustment. The link returned is not a permanent link. It expires after an hour.",
      "method": "GET",
      "path": "/adjustments/{adjustment_id}/credit-note",
      "path_params": [
        {
          "name": "adjustment_id",
          "required": true,
          "description": "Paddle ID of the adjustment entity to work with."
        }
      ],
      "query_params": [
        {
          "name": "disposition",
          "required": false,
          "description": "Determine whether the generated URL should download the PDF as an attachment saved locally, or open it inline in the browser. Default: `attachment`."
        }
      ],
      "header_params": [],
      "body_supported": false,
      "body_required": false,
      "body_required_keys": [],
      "permissions": [
        "adjustment.read"
      ],
      "docs_url": "https://developer.paddle.com/api-reference/adjustments/get-credit-note-pdf"
    },
    {
      "name": "list_businesses",
      "label": "List businesses for a customer",
      "category": "Businesses",
      "description": "Returns a paginated list of businesses for a customer. Use the query parameters to page through results. By default, Paddle returns businesses that are `active`. Use the `status` query parameter to return businesses that are archived.",
      "method": "GET",
      "path": "/customers/{customer_id}/businesses",
      "path_params": [
        {
          "name": "customer_id",
          "required": true,
          "description": "Paddle ID of the customer entity to work with."
        }
      ],
      "query_params": [
        {
          "name": "id",
          "required": false,
          "description": "Return only the IDs specified. Use a comma-separated list to get multiple entities."
        },
        {
          "name": "after",
          "required": false,
          "description": "Return entities after the specified Paddle ID when working with paginated endpoints. Used in the `meta.pagination.next` URL in responses for list operations."
        },
        {
          "name": "per_page",
          "required": false,
          "description": "Set how many entities are returned per page. Paddle returns the maximum number of results if a number greater than the maximum is requested. Check `meta.pagination.per_page` in the response to see how many were returned. Default: `50`; Maximum: `200`."
        },
        {
          "name": "order_by",
          "required": false,
          "description": "Order returned entities by the specified field and direction (`[ASC]` or `[DESC]`). For example, `?order_by=id[ASC]`. Valid fields for ordering: `id`."
        },
        {
          "name": "status",
          "required": false,
          "description": "Return entities that match the specified status. Use a comma-separated list to specify multiple status values."
        },
        {
          "name": "search",
          "required": false,
          "description": "Return entities that match a search query. Searches all fields, including contacts, except `status`, `created_at`, and `updated_at`."
        }
      ],
      "header_params": [
        {
          "name": "Skip-Count",
          "required": false,
          "description": "Set to `true` to skip the count query on list operations. When set, `meta.pagination.estimated_total` returns `-1` instead of an exact count."
        }
      ],
      "body_supported": false,
      "body_required": false,
      "body_required_keys": [],
      "permissions": [
        "business.read"
      ],
      "docs_url": "https://developer.paddle.com/api-reference/businesses/list-businesses"
    },
    {
      "name": "create_business",
      "label": "Create a business for a customer",
      "category": "Businesses",
      "description": "Creates a new business for a customer. If successful, your response includes a copy of the new business entity.",
      "method": "POST",
      "path": "/customers/{customer_id}/businesses",
      "path_params": [
        {
          "name": "customer_id",
          "required": true,
          "description": "Paddle ID of the customer entity to work with."
        }
      ],
      "query_params": [],
      "header_params": [],
      "body_supported": true,
      "body_required": true,
      "body_required_keys": [
        "name"
      ],
      "permissions": [
        "business.write"
      ],
      "docs_url": "https://developer.paddle.com/api-reference/businesses/create-business"
    },
    {
      "name": "get_business",
      "label": "Get a business for a customer",
      "category": "Businesses",
      "description": "Returns a business for a customer using its ID and related customer ID.",
      "method": "GET",
      "path": "/customers/{customer_id}/businesses/{business_id}",
      "path_params": [
        {
          "name": "business_id",
          "required": true,
          "description": "Paddle ID of the business entity to work with."
        },
        {
          "name": "customer_id",
          "required": true,
          "description": "Paddle ID of the customer entity to work with."
        }
      ],
      "query_params": [],
      "header_params": [],
      "body_supported": false,
      "body_required": false,
      "body_required_keys": [],
      "permissions": [
        "business.read"
      ],
      "docs_url": "https://developer.paddle.com/api-reference/businesses/get-business"
    },
    {
      "name": "update_business",
      "label": "Update a business for a customer",
      "category": "Businesses",
      "description": "Updates a business for a customer using its ID and related customer ID. If successful, your response includes a copy of the updated business entity.",
      "method": "PATCH",
      "path": "/customers/{customer_id}/businesses/{business_id}",
      "path_params": [
        {
          "name": "business_id",
          "required": true,
          "description": "Paddle ID of the business entity to work with."
        },
        {
          "name": "customer_id",
          "required": true,
          "description": "Paddle ID of the customer entity to work with."
        }
      ],
      "query_params": [],
      "header_params": [],
      "body_supported": true,
      "body_required": true,
      "body_required_keys": [],
      "permissions": [
        "business.write"
      ],
      "docs_url": "https://developer.paddle.com/api-reference/businesses/update-business"
    },
    {
      "name": "list_checkout_domains",
      "label": "List checkout domains",
      "category": "Checkout domains",
      "description": "Returns a paginated list of checkout domains submitted for your account. Use the query parameters to page through results.",
      "method": "GET",
      "path": "/checkout-domains",
      "path_params": [],
      "query_params": [
        {
          "name": "id",
          "required": false,
          "description": "Return only the IDs specified. Use a comma-separated list to get multiple entities."
        },
        {
          "name": "after",
          "required": false,
          "description": "Return entities after the specified Paddle ID when working with paginated endpoints. Used in the `meta.pagination.next` URL in responses for list operations."
        },
        {
          "name": "per_page",
          "required": false,
          "description": "Set how many entities are returned per page. Paddle returns the maximum number of results if a number greater than the maximum is requested. Check `meta.pagination.per_page` in the response to see how many were returned. Default: `50`; Maximum: `200`."
        },
        {
          "name": "domain",
          "required": false,
          "description": "Filter results to include the specified fully qualified domain name (FQDN), its ancestors, and any of its subdomains. For example, if you provide `app.example.com`, the results include `app.example.com`, `example.com` and any subdomains such as `cool.app.example.com`."
        },
        {
          "name": "order_by",
          "required": false,
          "description": "Order returned entities by the specified field and direction (`[ASC]` or `[DESC]`). For example, `?order_by=id[ASC]`. Valid fields for ordering: `id`, `created_at`, and `updated_at`."
        },
        {
          "name": "status",
          "required": false,
          "description": "Return entities that match the specified status. Use a comma-separated list to specify multiple status values."
        }
      ],
      "header_params": [
        {
          "name": "Skip-Count",
          "required": false,
          "description": "Set to `true` to skip the count query on list operations. When set, `meta.pagination.estimated_total` returns `-1` instead of an exact count."
        }
      ],
      "body_supported": false,
      "body_required": false,
      "body_required_keys": [],
      "permissions": [
        "checkout_domain.read"
      ],
      "docs_url": "https://developer.paddle.com/api-reference/checkout-domains/list-checkout-domains"
    },
    {
      "name": "get_checkout_domain",
      "label": "Get a checkout domain",
      "category": "Checkout domains",
      "description": "Returns a checkout domain using its ID. The response includes the domain's approval status and payment method verification details.",
      "method": "GET",
      "path": "/checkout-domains/{domain_id}",
      "path_params": [
        {
          "name": "domain_id",
          "required": true,
          "description": "Paddle ID of the checkout domain entity to work with."
        }
      ],
      "query_params": [],
      "header_params": [],
      "body_supported": false,
      "body_required": false,
      "body_required_keys": [],
      "permissions": [
        "checkout_domain.read"
      ],
      "docs_url": "https://developer.paddle.com/api-reference/checkout-domains/get-checkout-domain"
    },
    {
      "name": "delete_checkout_domain",
      "label": "Delete a checkout domain",
      "category": "Checkout domains",
      "description": "Deletes a checkout domain using its ID. Deleted checkout domains are no longer able to be used to load checkouts for your account.",
      "method": "DELETE",
      "path": "/checkout-domains/{domain_id}",
      "path_params": [
        {
          "name": "domain_id",
          "required": true,
          "description": "Paddle ID of the checkout domain entity to work with."
        }
      ],
      "query_params": [],
      "header_params": [],
      "body_supported": false,
      "body_required": false,
      "body_required_keys": [],
      "permissions": [
        "checkout_domain.write"
      ],
      "docs_url": "https://developer.paddle.com/api-reference/checkout-domains/delete-checkout-domain"
    },
    {
      "name": "verify_checkout_domain_payment_method",
      "label": "Verify a payment method for a checkout domain",
      "category": "Checkout domains",
      "description": "Triggers payment method verification for a checkout domain. Currently supports Apple Pay only. Before verifying, the checkout domain must be in `approved` status and the domain association file must be correctly hosted.",
      "method": "POST",
      "path": "/checkout-domains/{domain_id}/verify-payment-method",
      "path_params": [
        {
          "name": "domain_id",
          "required": true,
          "description": "Paddle ID of the checkout domain entity to work with."
        }
      ],
      "query_params": [],
      "header_params": [],
      "body_supported": true,
      "body_required": true,
      "body_required_keys": [
        "payment_method"
      ],
      "permissions": [
        "checkout_domain.write"
      ],
      "docs_url": "https://developer.paddle.com/api-reference/checkout-domains/verify-checkout-domain-payment-method"
    },
    {
      "name": "list_client_tokens",
      "label": "List client-side tokens",
      "category": "Client tokens",
      "description": "Returns a paginated list of client-side tokens. Use the query parameters to [page through results](https://developer.paddle.com/api-reference/about/pagination).",
      "method": "GET",
      "path": "/client-tokens",
      "path_params": [],
      "query_params": [
        {
          "name": "after",
          "required": false,
          "description": "Return entities after the specified Paddle ID when working with paginated endpoints. Used in the `meta.pagination.next` URL in responses for list operations."
        },
        {
          "name": "per_page",
          "required": false,
          "description": "Set how many entities are returned per page. Paddle returns the maximum number of results if a number greater than the maximum is requested. Check `meta.pagination.per_page` in the response to see how many were returned. Default: `50`; Maximum: `200`."
        },
        {
          "name": "order_by",
          "required": false,
          "description": "Order returned entities by the specified field and direction (`[ASC]` or `[DESC]`). For example, `?order_by=id[ASC]`. Valid fields for ordering: `id`."
        },
        {
          "name": "status",
          "required": false,
          "description": "Return entities that match the specified status. Use a comma-separated list to specify multiple status values."
        }
      ],
      "header_params": [
        {
          "name": "Skip-Count",
          "required": false,
          "description": "Set to `true` to skip the count query on list operations. When set, `meta.pagination.estimated_total` returns `-1` instead of an exact count."
        }
      ],
      "body_supported": false,
      "body_required": false,
      "body_required_keys": [],
      "permissions": [
        "client_token.read"
      ],
      "docs_url": "https://developer.paddle.com/api-reference/client-tokens/list-client-tokens"
    },
    {
      "name": "create_client_token",
      "label": "Create a client-side token",
      "category": "Client tokens",
      "description": "Creates a new client-side token. If successful, your response includes a copy of the new client-side token entity.",
      "method": "POST",
      "path": "/client-tokens",
      "path_params": [],
      "query_params": [],
      "header_params": [],
      "body_supported": true,
      "body_required": true,
      "body_required_keys": [
        "name"
      ],
      "permissions": [
        "client_token.write"
      ],
      "docs_url": "https://developer.paddle.com/api-reference/client-tokens/create-client-token"
    },
    {
      "name": "get_client_token",
      "label": "Get a client-side token",
      "category": "Client tokens",
      "description": "Returns a client-side token using its ID.",
      "method": "GET",
      "path": "/client-tokens/{client_token_id}",
      "path_params": [
        {
          "name": "client_token_id",
          "required": true,
          "description": "Paddle ID of the client-side token entity."
        }
      ],
      "query_params": [],
      "header_params": [],
      "body_supported": false,
      "body_required": false,
      "body_required_keys": [],
      "permissions": [
        "client_token.read"
      ],
      "docs_url": "https://developer.paddle.com/api-reference/client-tokens/get-client-token"
    },
    {
      "name": "update_client_token",
      "label": "Update a client-side token",
      "category": "Client tokens",
      "description": "Updates a client-side token using its ID. You can revoke a client-side token by changing its `status` to `revoked`. Client-side tokens that are revoked can't be updated to `active`. If successful, your response includes a copy of the updated client-side token entity.",
      "method": "PATCH",
      "path": "/client-tokens/{client_token_id}",
      "path_params": [
        {
          "name": "client_token_id",
          "required": true,
          "description": "Paddle ID of the client-side token entity."
        }
      ],
      "query_params": [],
      "header_params": [],
      "body_supported": true,
      "body_required": true,
      "body_required_keys": [
        "status"
      ],
      "permissions": [
        "client_token.write"
      ],
      "docs_url": "https://developer.paddle.com/api-reference/client-tokens/update-client-token"
    },
    {
      "name": "list_customers",
      "label": "List customers",
      "category": "Customers",
      "description": "Returns a paginated list of customers. Use the query parameters to page through results. By default, Paddle returns customers that are `active`. Use the `status` query parameter to return customers that are archived.",
      "method": "GET",
      "path": "/customers",
      "path_params": [],
      "query_params": [
        {
          "name": "id",
          "required": false,
          "description": "Return only the IDs specified. Use a comma-separated list to get multiple entities."
        },
        {
          "name": "after",
          "required": false,
          "description": "Return entities after the specified Paddle ID when working with paginated endpoints. Used in the `meta.pagination.next` URL in responses for list operations."
        },
        {
          "name": "per_page",
          "required": false,
          "description": "Set how many entities are returned per page. Paddle returns the maximum number of results if a number greater than the maximum is requested. Check `meta.pagination.per_page` in the response to see how many were returned. Default: `50`; Maximum: `200`."
        },
        {
          "name": "email",
          "required": false,
          "description": "Return entities that exactly match the specified email address. Use a comma-separated list to specify multiple email addresses. Recommended for precise matching of email addresses."
        },
        {
          "name": "order_by",
          "required": false,
          "description": "Order returned entities by the specified field and direction (`[ASC]` or `[DESC]`). For example, `?order_by=id[ASC]`. Valid fields for ordering: `id`."
        },
        {
          "name": "status",
          "required": false,
          "description": "Return entities that match the specified status. Use a comma-separated list to specify multiple status values."
        },
        {
          "name": "search",
          "required": false,
          "description": "Return entities that match a search query. Searches `id`, `name`, and `email` fields. Use the `email` query parameter for precise matching of email addresses."
        }
      ],
      "header_params": [
        {
          "name": "Skip-Count",
          "required": false,
          "description": "Set to `true` to skip the count query on list operations. When set, `meta.pagination.estimated_total` returns `-1` instead of an exact count."
        }
      ],
      "body_supported": false,
      "body_required": false,
      "body_required_keys": [],
      "permissions": [
        "customer.read"
      ],
      "docs_url": "https://developer.paddle.com/api-reference/customers/list-customers"
    },
    {
      "name": "create_customer",
      "label": "Create a customer",
      "category": "Customers",
      "description": "Creates a new customer. If successful, your response includes a copy of the new customer entity.",
      "method": "POST",
      "path": "/customers",
      "path_params": [],
      "query_params": [],
      "header_params": [],
      "body_supported": true,
      "body_required": true,
      "body_required_keys": [
        "email"
      ],
      "permissions": [
        "customer.write"
      ],
      "docs_url": "https://developer.paddle.com/api-reference/customers/create-customer"
    },
    {
      "name": "get_customer",
      "label": "Get a customer",
      "category": "Customers",
      "description": "Returns a customer using its ID.",
      "method": "GET",
      "path": "/customers/{customer_id}",
      "path_params": [
        {
          "name": "customer_id",
          "required": true,
          "description": "Paddle ID of the customer entity to work with."
        }
      ],
      "query_params": [],
      "header_params": [],
      "body_supported": false,
      "body_required": false,
      "body_required_keys": [],
      "permissions": [
        "customer.read"
      ],
      "docs_url": "https://developer.paddle.com/api-reference/customers/get-customer"
    },
    {
      "name": "update_customer",
      "label": "Update a customer",
      "category": "Customers",
      "description": "Updates a customer using its ID. If successful, your response includes a copy of the updated customer entity.",
      "method": "PATCH",
      "path": "/customers/{customer_id}",
      "path_params": [
        {
          "name": "customer_id",
          "required": true,
          "description": "Paddle ID of the customer entity to work with."
        }
      ],
      "query_params": [],
      "header_params": [],
      "body_supported": true,
      "body_required": true,
      "body_required_keys": [],
      "permissions": [
        "customer.write"
      ],
      "docs_url": "https://developer.paddle.com/api-reference/customers/update-customer"
    },
    {
      "name": "list_credit_balances",
      "label": "List credit balances for a customer",
      "category": "Customers",
      "description": "Returns a list of credit balances for each currency for a customer. Each balance has three totals: * `available`: total available to use. * `reserved`: total temporarily reserved for billed transactions. * `used`: total amount of credit used. Credit is added to the `available` total initially. When ",
      "method": "GET",
      "path": "/customers/{customer_id}/credit-balances",
      "path_params": [
        {
          "name": "customer_id",
          "required": true,
          "description": "Paddle ID of the customer entity to work with."
        }
      ],
      "query_params": [
        {
          "name": "currency_code",
          "required": false,
          "description": "Return entities that match the currency code. Use a comma-separated list to specify multiple currency codes."
        }
      ],
      "header_params": [],
      "body_supported": false,
      "body_required": false,
      "body_required_keys": [],
      "permissions": [
        "customer.read"
      ],
      "docs_url": "https://developer.paddle.com/api-reference/customers/list-credit-balances"
    },
    {
      "name": "generate_customer_authentication_token",
      "label": "Generate an authentication token for a customer",
      "category": "Customers",
      "description": "Generates an authentication token for a customer. You can pass a generated authentication token to Paddle.js when opening a checkout to let customers work with saved payment methods. Authentication tokens are temporary and shouldn't be cached. They're valid until the `expires_at` date returned in th",
      "method": "POST",
      "path": "/customers/{customer_id}/auth-token",
      "path_params": [
        {
          "name": "customer_id",
          "required": true,
          "description": "Paddle ID of the customer entity to work with."
        }
      ],
      "query_params": [],
      "header_params": [],
      "body_supported": false,
      "body_required": false,
      "body_required_keys": [],
      "permissions": [
        "customer_auth_token.write"
      ],
      "docs_url": "https://developer.paddle.com/api-reference/customers/generate-customer-authentication-token"
    },
    {
      "name": "create_customer_portal_session",
      "label": "Create a customer portal session",
      "category": "Customer portals",
      "description": "Creates a customer portal session for a customer. The [customer portal](https://developer.paddle.com/concepts/customer-portal) is a secure, Paddle-hosted site that allows customers to manage their own subscriptions, payments, and account information without you having to build custom billing screens",
      "method": "POST",
      "path": "/customers/{customer_id}/portal-sessions",
      "path_params": [
        {
          "name": "customer_id",
          "required": true,
          "description": "Paddle ID of the customer entity to work with."
        }
      ],
      "query_params": [],
      "header_params": [],
      "body_supported": true,
      "body_required": true,
      "body_required_keys": [],
      "permissions": [
        "customer_portal_session.write"
      ],
      "docs_url": "https://developer.paddle.com/api-reference/customer-portals/create-customer-portal-session"
    },
    {
      "name": "list_discount_groups",
      "label": "List discount groups",
      "category": "Discount groups",
      "description": "Returns a paginated list of discount groups. Use the query parameters to page through results.",
      "method": "GET",
      "path": "/discount-groups",
      "path_params": [],
      "query_params": [
        {
          "name": "id",
          "required": false,
          "description": "Return only the IDs specified. Use a comma-separated list to get multiple entities."
        },
        {
          "name": "after",
          "required": false,
          "description": "Return entities after the specified Paddle ID when working with paginated endpoints. Used in the `meta.pagination.next` URL in responses for list operations."
        },
        {
          "name": "per_page",
          "required": false,
          "description": "Set how many entities are returned per page. Paddle returns the maximum number of results if a number greater than the maximum is requested. Check `meta.pagination.per_page` in the response to see how many were returned. Default: `50`; Maximum: `200`."
        },
        {
          "name": "order_by",
          "required": false,
          "description": "Order returned entities by the specified field and direction (`[ASC]` or `[DESC]`). For example, `?order_by=id[ASC]`. Valid fields for ordering: `created_at` and `id`."
        }
      ],
      "header_params": [
        {
          "name": "Skip-Count",
          "required": false,
          "description": "Set to `true` to skip the count query on list operations. When set, `meta.pagination.estimated_total` returns `-1` instead of an exact count."
        }
      ],
      "body_supported": false,
      "body_required": false,
      "body_required_keys": [],
      "permissions": [
        "discount.read"
      ],
      "docs_url": "https://developer.paddle.com/api-reference/discount-groups/list-discount-groups"
    },
    {
      "name": "create_discount_group",
      "label": "Create a discount group",
      "category": "Discount groups",
      "description": "Creates a new discount group. If successful, your response includes a copy of the new discount group entity.",
      "method": "POST",
      "path": "/discount-groups",
      "path_params": [],
      "query_params": [],
      "header_params": [],
      "body_supported": true,
      "body_required": true,
      "body_required_keys": [
        "name"
      ],
      "permissions": [
        "discount.write"
      ],
      "docs_url": "https://developer.paddle.com/api-reference/discount-groups/create-discount-group"
    },
    {
      "name": "get_discount_group",
      "label": "Get a discount group",
      "category": "Discount groups",
      "description": "Returns a discount group using its ID.",
      "method": "GET",
      "path": "/discount-groups/{discount_group_id}",
      "path_params": [
        {
          "name": "discount_group_id",
          "required": true,
          "description": "Paddle ID of the discount group entity to work with."
        }
      ],
      "query_params": [],
      "header_params": [],
      "body_supported": false,
      "body_required": false,
      "body_required_keys": [],
      "permissions": [
        "discount.read"
      ],
      "docs_url": "https://developer.paddle.com/api-reference/discount-groups/get-discount-group"
    },
    {
      "name": "update_discount_group",
      "label": "Update a discount group",
      "category": "Discount groups",
      "description": "Updates a discount group using its ID. If successful, your response includes a copy of the updated discount group entity.",
      "method": "PATCH",
      "path": "/discount-groups/{discount_group_id}",
      "path_params": [
        {
          "name": "discount_group_id",
          "required": true,
          "description": "Paddle ID of the discount group entity to work with."
        }
      ],
      "query_params": [],
      "header_params": [],
      "body_supported": true,
      "body_required": true,
      "body_required_keys": [],
      "permissions": [
        "discount.write"
      ],
      "docs_url": "https://developer.paddle.com/api-reference/discount-groups/update-discount-group"
    },
    {
      "name": "list_discounts",
      "label": "List discounts",
      "category": "Discounts",
      "description": "Returns a paginated list of discounts. Use the query parameters to page through results. By default, Paddle returns discounts that are `active`. Use the `status` query parameter to return discounts that are archived or expired.",
      "method": "GET",
      "path": "/discounts",
      "path_params": [],
      "query_params": [
        {
          "name": "id",
          "required": false,
          "description": "Return only the IDs specified. Use a comma-separated list to get multiple entities."
        },
        {
          "name": "after",
          "required": false,
          "description": "Return entities after the specified Paddle ID when working with paginated endpoints. Used in the `meta.pagination.next` URL in responses for list operations."
        },
        {
          "name": "per_page",
          "required": false,
          "description": "Set how many entities are returned per page. Paddle returns the maximum number of results if a number greater than the maximum is requested. Check `meta.pagination.per_page` in the response to see how many were returned. Default: `50`; Maximum: `200`."
        },
        {
          "name": "include",
          "required": false,
          "description": "Include related entities in the response. Use a comma-separated list to specify multiple entities."
        },
        {
          "name": "code",
          "required": false,
          "description": "Return entities that match the discount code. Use a comma-separated list to specify multiple discount codes."
        },
        {
          "name": "order_by",
          "required": false,
          "description": "Order returned entities by the specified field and direction (`[ASC]` or `[DESC]`). For example, `?order_by=id[ASC]`. Valid fields for ordering: `created_at` and `id`."
        },
        {
          "name": "status",
          "required": false,
          "description": "Return entities that match the specified status. Use a comma-separated list to specify multiple status values."
        },
        {
          "name": "mode",
          "required": false,
          "description": "Return entities that match the specified mode."
        },
        {
          "name": "discount_group_id",
          "required": false,
          "description": "Return entities related to the specified discount group. Use a comma-separated list to specify multiple discount group IDs."
        }
      ],
      "header_params": [
        {
          "name": "Skip-Count",
          "required": false,
          "description": "Set to `true` to skip the count query on list operations. When set, `meta.pagination.estimated_total` returns `-1` instead of an exact count."
        }
      ],
      "body_supported": false,
      "body_required": false,
      "body_required_keys": [],
      "permissions": [
        "discount.read"
      ],
      "docs_url": "https://developer.paddle.com/api-reference/discounts/list-discounts"
    },
    {
      "name": "create_discount",
      "label": "Create a discount",
      "category": "Discounts",
      "description": "Creates a new discount. If successful, your response includes a copy of the new discount entity.",
      "method": "POST",
      "path": "/discounts",
      "path_params": [],
      "query_params": [],
      "header_params": [],
      "body_supported": true,
      "body_required": true,
      "body_required_keys": [
        "amount",
        "description",
        "type"
      ],
      "permissions": [
        "discount.write"
      ],
      "docs_url": "https://developer.paddle.com/api-reference/discounts/create-discount"
    },
    {
      "name": "get_discount",
      "label": "Get a discount",
      "category": "Discounts",
      "description": "Returns a discount using its ID.",
      "method": "GET",
      "path": "/discounts/{discount_id}",
      "path_params": [
        {
          "name": "discount_id",
          "required": true,
          "description": "Paddle ID of the discount entity to work with."
        }
      ],
      "query_params": [
        {
          "name": "include",
          "required": false,
          "description": "Include related entities in the response. Use a comma-separated list to specify multiple entities."
        }
      ],
      "header_params": [],
      "body_supported": false,
      "body_required": false,
      "body_required_keys": [],
      "permissions": [
        "discount.read"
      ],
      "docs_url": "https://developer.paddle.com/api-reference/discounts/get-discount"
    },
    {
      "name": "update_discount",
      "label": "Update a discount",
      "category": "Discounts",
      "description": "Updates a discount using its ID. If successful, your response includes a copy of the updated discount entity. To update a checkout recovery discount, configure your checkout recovery settings in the dashboard.",
      "method": "PATCH",
      "path": "/discounts/{discount_id}",
      "path_params": [
        {
          "name": "discount_id",
          "required": true,
          "description": "Paddle ID of the discount entity to work with."
        }
      ],
      "query_params": [],
      "header_params": [],
      "body_supported": true,
      "body_required": true,
      "body_required_keys": [],
      "permissions": [
        "discount.write"
      ],
      "docs_url": "https://developer.paddle.com/api-reference/discounts/update-discount"
    },
    {
      "name": "list_event_types",
      "label": "List events types",
      "category": "Event types",
      "description": "Returns a list of event types. The response is not paginated.",
      "method": "GET",
      "path": "/event-types",
      "path_params": [],
      "query_params": [],
      "header_params": [],
      "body_supported": false,
      "body_required": false,
      "body_required_keys": [],
      "permissions": [],
      "docs_url": "https://developer.paddle.com/api-reference/event-types/list-event-types"
    },
    {
      "name": "list_events",
      "label": "List events",
      "category": "Events",
      "description": "Returns a paginated list of events that have occurred in the last 90 days. Use the query parameters to page through results. Events older than 90 days aren't retained. This is sometimes referred to as \"the event stream.\"",
      "method": "GET",
      "path": "/events",
      "path_params": [],
      "query_params": [
        {
          "name": "after",
          "required": false,
          "description": "Return entities after the specified Paddle ID when working with paginated endpoints. Used in the `meta.pagination.next` URL in responses for list operations."
        },
        {
          "name": "per_page",
          "required": false,
          "description": "Set how many entities are returned per page. Paddle returns the maximum number of results if a number greater than the maximum is requested. Check `meta.pagination.per_page` in the response to see how many were returned. Default: `50`; Maximum: `200`."
        },
        {
          "name": "order_by",
          "required": false,
          "description": "Order returned entities by the specified field and direction (`[ASC]` or `[DESC]`). For example, `?order_by=id[ASC]`. Valid fields for ordering: `id` (for `event_id`)."
        },
        {
          "name": "event_type",
          "required": false,
          "description": "Return events that match the specified event type. Use a comma-separated list to specify multiple event types."
        }
      ],
      "header_params": [
        {
          "name": "Skip-Count",
          "required": false,
          "description": "Set to `true` to skip the count query on list operations. When set, `meta.pagination.estimated_total` returns `-1` instead of an exact count."
        }
      ],
      "body_supported": false,
      "body_required": false,
      "body_required_keys": [],
      "permissions": [
        "notification.read"
      ],
      "docs_url": "https://developer.paddle.com/api-reference/events/list-events"
    },
    {
      "name": "get_ip_addresses",
      "label": "Get Paddle IP addresses",
      "category": "IP addresses",
      "description": "Returns Paddle IP addresses. You can add these IP addresses to your allowlist. IP addresses returned are for the environment that you're making the request in. For example, making the request to the production base URL returns all production IP addresses.",
      "method": "GET",
      "path": "/ips",
      "path_params": [],
      "query_params": [],
      "header_params": [],
      "body_supported": false,
      "body_required": false,
      "body_required_keys": [],
      "permissions": [],
      "docs_url": "https://developer.paddle.com/api-reference/"
    },
    {
      "name": "get_metrics_monthly_recurring_revenue",
      "label": "Get MRR (monthly recurring revenue) metrics",
      "category": "Metrics",
      "description": "Returns timeseries data for monthly recurring revenue in a given date range. Trends have a daily granularity. Current monthly recurring revenue total. Includes new subscriptions, upgrades, downgrades and churn. Does not include one-time payments or deductions for Paddle fees. When `to` and `from` ar",
      "method": "GET",
      "path": "/metrics/monthly-recurring-revenue",
      "path_params": [],
      "query_params": [
        {
          "name": "from",
          "required": true,
          "description": "Return data from a specific date. Pass an RFC 3339 full-date string. Interpreted at 00:00 UTC. Must be before or the same as `to`."
        },
        {
          "name": "to",
          "required": true,
          "description": "Return data up to a specific date. Pass an RFC 3339 full-date string. Interpreted as 00:00 UTC. Must be after or the same as `from`."
        }
      ],
      "header_params": [],
      "body_supported": false,
      "body_required": false,
      "body_required_keys": [],
      "permissions": [
        "metrics.read"
      ],
      "docs_url": "https://developer.paddle.com/api-reference/"
    },
    {
      "name": "get_metrics_active_subscribers",
      "label": "Get active subscribers metrics",
      "category": "Metrics",
      "description": "Returns timeseries data for active subscriber counts in a given date range. Trends have a daily granularity. Current number of paying users with active subscriptions (does not include trialling users). When `to` and `from` are the same, returns an empty timeseries.",
      "method": "GET",
      "path": "/metrics/active-subscribers",
      "path_params": [],
      "query_params": [
        {
          "name": "from",
          "required": true,
          "description": "Return data from a specific date. Pass an RFC 3339 full-date string. Interpreted at 00:00 UTC. Must be before or the same as `to`."
        },
        {
          "name": "to",
          "required": true,
          "description": "Return data up to a specific date. Pass an RFC 3339 full-date string. Interpreted as 00:00 UTC. Must be after or the same as `from`."
        }
      ],
      "header_params": [],
      "body_supported": false,
      "body_required": false,
      "body_required_keys": [],
      "permissions": [
        "metrics.read"
      ],
      "docs_url": "https://developer.paddle.com/api-reference/"
    },
    {
      "name": "get_metrics_monthly_recurring_revenue_change",
      "label": "Get MRR change (monthly recurring revenue change) metrics",
      "category": "Metrics",
      "description": "Returns timeseries data for monthly recurring revenue change in a given date range. Trends have a daily granularity. Monthly recurring revenue (MRR) change compared to the same time interval last month. When `to` and `from` are the same, returns an empty timeseries.",
      "method": "GET",
      "path": "/metrics/monthly-recurring-revenue-change",
      "path_params": [],
      "query_params": [
        {
          "name": "from",
          "required": true,
          "description": "Return data from a specific date. Pass an RFC 3339 full-date string. Interpreted at 00:00 UTC. Must be before or the same as `to`."
        },
        {
          "name": "to",
          "required": true,
          "description": "Return data up to a specific date. Pass an RFC 3339 full-date string. Interpreted as 00:00 UTC. Must be after or the same as `from`."
        }
      ],
      "header_params": [],
      "body_supported": false,
      "body_required": false,
      "body_required_keys": [],
      "permissions": [
        "metrics.read"
      ],
      "docs_url": "https://developer.paddle.com/api-reference/"
    },
    {
      "name": "get_metrics_revenue",
      "label": "Get net revenue metrics",
      "category": "Metrics",
      "description": "Returns timeseries data for revenue in a given date range. Trends have a daily granularity. Net revenue from completed payments (e.g. single purchase, subscription, B2B invoices) after tax & fees have been deducted, but before adjustments such as refunds or chargebacks. When `to` and `from` are the ",
      "method": "GET",
      "path": "/metrics/revenue",
      "path_params": [],
      "query_params": [
        {
          "name": "from",
          "required": true,
          "description": "Return data from a specific date. Pass an RFC 3339 full-date string. Interpreted at 00:00 UTC. Must be before or the same as `to`."
        },
        {
          "name": "to",
          "required": true,
          "description": "Return data up to a specific date. Pass an RFC 3339 full-date string. Interpreted as 00:00 UTC. Must be after or the same as `from`."
        }
      ],
      "header_params": [],
      "body_supported": false,
      "body_required": false,
      "body_required_keys": [],
      "permissions": [
        "metrics.read"
      ],
      "docs_url": "https://developer.paddle.com/api-reference/"
    },
    {
      "name": "get_metrics_refunds",
      "label": "Get refund metrics",
      "category": "Metrics",
      "description": "Returns timeseries data for refunds in a given date range. Trends have a daily granularity. The transaction subtotal (base cost minus discounts excluding taxes and fees) of refunded products returned to the customer. This does not include chargebacks. When `to` and `from` are the same, returns an em",
      "method": "GET",
      "path": "/metrics/refunds",
      "path_params": [],
      "query_params": [
        {
          "name": "from",
          "required": true,
          "description": "Return data from a specific date. Pass an RFC 3339 full-date string. Interpreted at 00:00 UTC. Must be before or the same as `to`."
        },
        {
          "name": "to",
          "required": true,
          "description": "Return data up to a specific date. Pass an RFC 3339 full-date string. Interpreted as 00:00 UTC. Must be after or the same as `from`."
        }
      ],
      "header_params": [],
      "body_supported": false,
      "body_required": false,
      "body_required_keys": [],
      "permissions": [
        "metrics.read"
      ],
      "docs_url": "https://developer.paddle.com/api-reference/"
    },
    {
      "name": "get_metrics_chargebacks",
      "label": "Get chargeback metrics",
      "category": "Metrics",
      "description": "Returns timeseries data for chargebacks in a given date range. Trends have a daily granularity. Total number of chargebacks received for the period. Does not include pre-chargeback alerts or chargeback reversals. When `to` and `from` are the same, returns an empty timeseries.",
      "method": "GET",
      "path": "/metrics/chargebacks",
      "path_params": [],
      "query_params": [
        {
          "name": "from",
          "required": true,
          "description": "Return data from a specific date. Pass an RFC 3339 full-date string. Interpreted at 00:00 UTC. Must be before or the same as `to`."
        },
        {
          "name": "to",
          "required": true,
          "description": "Return data up to a specific date. Pass an RFC 3339 full-date string. Interpreted as 00:00 UTC. Must be after or the same as `from`."
        }
      ],
      "header_params": [],
      "body_supported": false,
      "body_required": false,
      "body_required_keys": [],
      "permissions": [
        "metrics.read"
      ],
      "docs_url": "https://developer.paddle.com/api-reference/"
    },
    {
      "name": "get_metrics_checkout_conversion",
      "label": "Get checkout conversion metrics",
      "category": "Metrics",
      "description": "Returns timeseries data for checkout conversion in a given date range. Trends have a daily granularity. The conversion rate for checkouts in the period. A checkout is considered converted when a payment is successfully completed. When `to` and `from` are the same, returns an empty timeseries.",
      "method": "GET",
      "path": "/metrics/checkout-conversion",
      "path_params": [],
      "query_params": [
        {
          "name": "from",
          "required": true,
          "description": "Return data from a specific date. Pass an RFC 3339 full-date string. Interpreted at 00:00 UTC. Must be before or the same as `to`."
        },
        {
          "name": "to",
          "required": true,
          "description": "Return data up to a specific date. Pass an RFC 3339 full-date string. Interpreted as 00:00 UTC. Must be after or the same as `from`."
        }
      ],
      "header_params": [],
      "body_supported": false,
      "body_required": false,
      "body_required_keys": [],
      "permissions": [
        "metrics.read"
      ],
      "docs_url": "https://developer.paddle.com/api-reference/"
    },
    {
      "name": "list_notification_settings",
      "label": "List notification settings",
      "category": "Notification settings",
      "description": "Returns a paginated list of notification settings (notification destinations).",
      "method": "GET",
      "path": "/notification-settings",
      "path_params": [],
      "query_params": [
        {
          "name": "after",
          "required": false,
          "description": "Return entities after the specified Paddle ID when working with paginated endpoints. Used in the `meta.pagination.next` URL in responses for list operations."
        },
        {
          "name": "per_page",
          "required": false,
          "description": "Set how many entities are returned per page. Paddle returns the maximum number of results if a number greater than the maximum is requested. Check `meta.pagination.per_page` in the response to see how many were returned. Default: `200`; Maximum: `200`."
        },
        {
          "name": "order_by",
          "required": false,
          "description": "Order returned entities by the specified field and direction (`[ASC]` or `[DESC]`). For example, `?order_by=id[ASC]`. Valid fields for ordering: `id`."
        },
        {
          "name": "active",
          "required": false,
          "description": "Determine whether returned entities are active (`true`) or not (`false`)."
        },
        {
          "name": "traffic_source",
          "required": false,
          "description": "Return entities that match the specified traffic source."
        }
      ],
      "header_params": [
        {
          "name": "Skip-Count",
          "required": false,
          "description": "Set to `true` to skip the count query on list operations. When set, `meta.pagination.estimated_total` returns `-1` instead of an exact count."
        }
      ],
      "body_supported": false,
      "body_required": false,
      "body_required_keys": [],
      "permissions": [
        "notification_setting.read"
      ],
      "docs_url": "https://developer.paddle.com/api-reference/notification-settings/list-notification-settings"
    },
    {
      "name": "create_notification_setting",
      "label": "Create a notification setting",
      "category": "Notification settings",
      "description": "Creates a new notification setting (notification destination). Pass an array of event type names to `subscribed_events` to say which events you'd like to subscribe to. Paddle responds with the full event type object for each event type. If successful, your response includes a copy of the new notific",
      "method": "POST",
      "path": "/notification-settings",
      "path_params": [],
      "query_params": [],
      "header_params": [],
      "body_supported": true,
      "body_required": true,
      "body_required_keys": [
        "description",
        "destination",
        "subscribed_events",
        "type"
      ],
      "permissions": [
        "notification_setting.write"
      ],
      "docs_url": "https://developer.paddle.com/api-reference/notification-settings/create-notification-setting"
    },
    {
      "name": "get_notification_setting",
      "label": "Get a notification setting",
      "category": "Notification settings",
      "description": "Returns a notification setting (notification destination) using its ID.",
      "method": "GET",
      "path": "/notification-settings/{notification_setting_id}",
      "path_params": [
        {
          "name": "notification_setting_id",
          "required": true,
          "description": "Paddle ID of the notification setting entity (notification destination) to work with."
        }
      ],
      "query_params": [],
      "header_params": [],
      "body_supported": false,
      "body_required": false,
      "body_required_keys": [],
      "permissions": [
        "notification_setting.read"
      ],
      "docs_url": "https://developer.paddle.com/api-reference/notification-settings/get-notification-setting"
    },
    {
      "name": "update_notification_setting",
      "label": "Update a notification setting",
      "category": "Notification settings",
      "description": "Updates a notification setting (notification destination) using its ID. When updating subscribed events, send the complete list of event types that you'd like to subscribe to — including existing event types. If you omit event types, they're removed from the notification setting. You only need to pa",
      "method": "PATCH",
      "path": "/notification-settings/{notification_setting_id}",
      "path_params": [
        {
          "name": "notification_setting_id",
          "required": true,
          "description": "Paddle ID of the notification setting entity (notification destination) to work with."
        }
      ],
      "query_params": [],
      "header_params": [],
      "body_supported": true,
      "body_required": true,
      "body_required_keys": [],
      "permissions": [
        "notification_setting.write"
      ],
      "docs_url": "https://developer.paddle.com/api-reference/notification-settings/update-notification-setting"
    },
    {
      "name": "delete_notification_setting",
      "label": "Delete a notification setting",
      "category": "Notification settings",
      "description": "Deletes a notification setting (notification destination) using its ID. When you delete a notification setting, it's permanently removed from your account. Paddle stops sending events to your destination, and you'll lose access to all the logs for this notification setting. There's no way to recover",
      "method": "DELETE",
      "path": "/notification-settings/{notification_setting_id}",
      "path_params": [
        {
          "name": "notification_setting_id",
          "required": true,
          "description": "Paddle ID of the notification setting entity (notification destination) to work with."
        }
      ],
      "query_params": [],
      "header_params": [],
      "body_supported": false,
      "body_required": false,
      "body_required_keys": [],
      "permissions": [
        "notification_setting.write"
      ],
      "docs_url": "https://developer.paddle.com/api-reference/notification-settings/delete-notification-setting"
    },
    {
      "name": "list_notifications",
      "label": "List notifications",
      "category": "Notifications",
      "description": "Returns a paginated list of notifications created in the last 90 days. Use the query parameters to page through results. Notifications older than 90 days aren't retained.",
      "method": "GET",
      "path": "/notifications",
      "path_params": [],
      "query_params": [
        {
          "name": "after",
          "required": false,
          "description": "Return entities after the specified Paddle ID when working with paginated endpoints. Used in the `meta.pagination.next` URL in responses for list operations."
        },
        {
          "name": "per_page",
          "required": false,
          "description": "Set how many entities are returned per page. Paddle returns the maximum number of results if a number greater than the maximum is requested. Check `meta.pagination.per_page` in the response to see how many were returned. Default: `50`; Maximum: `200`."
        },
        {
          "name": "notification_setting_id",
          "required": false,
          "description": "Return entities related to the specified notification destination. Use a comma-separated list to specify multiple notification destination IDs."
        },
        {
          "name": "order_by",
          "required": false,
          "description": "Order returned entities by the specified field and direction (`[ASC]` or `[DESC]`). For example, `?order_by=id[ASC]`. Valid fields for ordering: `id`."
        },
        {
          "name": "search",
          "required": false,
          "description": "Return entities that match a search query. Searches `id` and `type` fields."
        },
        {
          "name": "status",
          "required": false,
          "description": "Return entities that match the specified status. Use a comma-separated list to specify multiple status values."
        },
        {
          "name": "filter",
          "required": false,
          "description": "Return entities that contain the Paddle ID specified. Pass a transaction, customer, or subscription ID."
        },
        {
          "name": "to",
          "required": false,
          "description": "Return entities up to a specific time. Pass an RFC 3339 datetime string."
        },
        {
          "name": "from",
          "required": false,
          "description": "Return entities from a specific time. Pass an RFC 3339 datetime string."
        }
      ],
      "header_params": [
        {
          "name": "Skip-Count",
          "required": false,
          "description": "Set to `true` to skip the count query on list operations. When set, `meta.pagination.estimated_total` returns `-1` instead of an exact count."
        }
      ],
      "body_supported": false,
      "body_required": false,
      "body_required_keys": [],
      "permissions": [
        "notification.read"
      ],
      "docs_url": "https://developer.paddle.com/api-reference/notifications/list-notifications"
    },
    {
      "name": "get_notification",
      "label": "Get a notification",
      "category": "Notifications",
      "description": "Returns a notification using its ID. Notifications older than 90 days aren't retained. If you try to get a notification that's no longer retained, Paddle returns an error.",
      "method": "GET",
      "path": "/notifications/{notification_id}",
      "path_params": [
        {
          "name": "notification_id",
          "required": true,
          "description": "Paddle ID of the notification entity to work with."
        }
      ],
      "query_params": [],
      "header_params": [],
      "body_supported": false,
      "body_required": false,
      "body_required_keys": [],
      "permissions": [
        "notification.read"
      ],
      "docs_url": "https://developer.paddle.com/api-reference/notifications/get-notification"
    },
    {
      "name": "list_notification_logs",
      "label": "List logs for a notification",
      "category": "Notification logs",
      "description": "Returns a paginated list of notification logs for a notification. A log includes information about delivery attempts, including failures. Notifications older than 90 days aren't retained. If you try to list logs for a notification that's no longer retained, Paddle returns an error.",
      "method": "GET",
      "path": "/notifications/{notification_id}/logs",
      "path_params": [
        {
          "name": "notification_id",
          "required": true,
          "description": "Paddle ID of the notification entity to work with."
        }
      ],
      "query_params": [
        {
          "name": "after",
          "required": false,
          "description": "Return entities after the specified Paddle ID when working with paginated endpoints. Used in the `meta.pagination.next` URL in responses for list operations."
        },
        {
          "name": "per_page",
          "required": false,
          "description": "Set how many entities are returned per page. Paddle returns the maximum number of results if a number greater than the maximum is requested. Check `meta.pagination.per_page` in the response to see how many were returned. Default: `50`; Maximum: `200`."
        }
      ],
      "header_params": [
        {
          "name": "Skip-Count",
          "required": false,
          "description": "Set to `true` to skip the count query on list operations. When set, `meta.pagination.estimated_total` returns `-1` instead of an exact count."
        }
      ],
      "body_supported": false,
      "body_required": false,
      "body_required_keys": [],
      "permissions": [
        "notification.read"
      ],
      "docs_url": "https://developer.paddle.com/api-reference/notification-logs/list-notification-logs"
    },
    {
      "name": "replay_notification",
      "label": "Replay a notification",
      "category": "Notifications",
      "description": "Attempts to resend a `delivered` or `failed` notification using its ID. Paddle creates a new notification entity for the replay, related to the same `event_id`. Your response includes the new `notification_id` of the created notification. Notifications older than 90 days aren't retained. If you try ",
      "method": "POST",
      "path": "/notifications/{notification_id}/replay",
      "path_params": [
        {
          "name": "notification_id",
          "required": true,
          "description": "Paddle ID of the notification entity to work with."
        }
      ],
      "query_params": [],
      "header_params": [],
      "body_supported": false,
      "body_required": false,
      "body_required_keys": [],
      "permissions": [
        "notification.write"
      ],
      "docs_url": "https://developer.paddle.com/api-reference/notifications/replay-notification"
    },
    {
      "name": "list_customer_payment_methods",
      "label": "List payment methods for a customer",
      "category": "Payment methods",
      "description": "Returns a paginated list of payment methods that a customer has saved. Use the query parameters to page through results. Customers can choose to save payment methods when purchasing one-time items and subscriptions by checking a box when completing checkout. You can present customers with their save",
      "method": "GET",
      "path": "/customers/{customer_id}/payment-methods",
      "path_params": [
        {
          "name": "customer_id",
          "required": true,
          "description": "Paddle ID of the customer entity to work with."
        }
      ],
      "query_params": [
        {
          "name": "after",
          "required": false,
          "description": "Return entities after the specified Paddle ID when working with paginated endpoints. Used in the `meta.pagination.next` URL in responses for list operations."
        },
        {
          "name": "per_page",
          "required": false,
          "description": "Set how many entities are returned per page. Paddle returns the maximum number of results if a number greater than the maximum is requested. Check `meta.pagination.per_page` in the response to see how many were returned. Default: `50`; Maximum: `200`."
        },
        {
          "name": "address_id",
          "required": false,
          "description": "Return entities related to the specified address. Use a comma-separated list to specify multiple address IDs."
        },
        {
          "name": "order_by",
          "required": false,
          "description": "Order returned entities by the specified field and direction (`[ASC]` or `[DESC]`). For example, `?order_by=id[ASC]`. Valid fields for ordering: `id`."
        },
        {
          "name": "supports_checkout",
          "required": false,
          "description": "Return entities that support being presented at checkout (`true`) or not (`false`)."
        }
      ],
      "header_params": [
        {
          "name": "Skip-Count",
          "required": false,
          "description": "Set to `true` to skip the count query on list operations. When set, `meta.pagination.estimated_total` returns `-1` instead of an exact count."
        }
      ],
      "body_supported": false,
      "body_required": false,
      "body_required_keys": [],
      "permissions": [
        "payment_method.read"
      ],
      "docs_url": "https://developer.paddle.com/api-reference/payment-methods/list-payment-methods"
    },
    {
      "name": "get_customer_payment_method",
      "label": "Get a payment method for a customer",
      "category": "Payment methods",
      "description": "Returns a payment method for a customer using its ID and related customer ID.",
      "method": "GET",
      "path": "/customers/{customer_id}/payment-methods/{payment_method_id}",
      "path_params": [
        {
          "name": "customer_id",
          "required": true,
          "description": "Paddle ID of the customer entity to work with."
        },
        {
          "name": "payment_method_id",
          "required": true,
          "description": "Paddle ID of the payment method entity to work with."
        }
      ],
      "query_params": [],
      "header_params": [],
      "body_supported": false,
      "body_required": false,
      "body_required_keys": [],
      "permissions": [
        "payment_method.read"
      ],
      "docs_url": "https://developer.paddle.com/api-reference/payment-methods/get-payment-method"
    },
    {
      "name": "delete_customer_payment_method",
      "label": "Delete a payment method for a customer",
      "category": "Payment methods",
      "description": "Deletes a customer payment method using its ID. Deleted payment methods are no longer saved and presented to the customer for future purchases. Saved payment methods can't be deleted if tied to an `active`, `trialing`, `paused`, or `past_due` subscription. Update the subscription's payment method fi",
      "method": "DELETE",
      "path": "/customers/{customer_id}/payment-methods/{payment_method_id}",
      "path_params": [
        {
          "name": "customer_id",
          "required": true,
          "description": "Paddle ID of the customer entity to work with."
        },
        {
          "name": "payment_method_id",
          "required": true,
          "description": "Paddle ID of the payment method entity to work with."
        }
      ],
      "query_params": [],
      "header_params": [],
      "body_supported": false,
      "body_required": false,
      "body_required_keys": [],
      "permissions": [
        "payment_method.write"
      ],
      "docs_url": "https://developer.paddle.com/api-reference/payment-methods/delete-payment-method"
    },
    {
      "name": "list_prices",
      "label": "List prices",
      "category": "Prices",
      "description": "Returns a paginated list of prices. Use the query parameters to page through results. By default, Paddle returns prices that are `active`. Use the `status` query parameter to return prices that are archived. Use the `include` parameter to include the related product entity in the response.",
      "method": "GET",
      "path": "/prices",
      "path_params": [],
      "query_params": [
        {
          "name": "id",
          "required": false,
          "description": "Return only the IDs specified. Use a comma-separated list to get multiple entities."
        },
        {
          "name": "after",
          "required": false,
          "description": "Return entities after the specified Paddle ID when working with paginated endpoints. Used in the `meta.pagination.next` URL in responses for list operations."
        },
        {
          "name": "per_page",
          "required": false,
          "description": "Set how many entities are returned per page. Paddle returns the maximum number of results if a number greater than the maximum is requested. Check `meta.pagination.per_page` in the response to see how many were returned. Default: `50`; Maximum: `200`."
        },
        {
          "name": "include",
          "required": false,
          "description": "Include related entities in the response."
        },
        {
          "name": "order_by",
          "required": false,
          "description": "Order returned entities by the specified field and direction (`[ASC]` or `[DESC]`). For example, `?order_by=id[ASC]`. Valid fields for ordering: `billing_cycle.frequency`, `billing_cycle.interval`, `id`, `product_id`, `quantity.maximum`, `quantity.minimum`, `status`, `tax_mode`, `unit_price.amount`,"
        },
        {
          "name": "product_id",
          "required": false,
          "description": "Return entities related to the specified product. Use a comma-separated list to specify multiple product IDs."
        },
        {
          "name": "status",
          "required": false,
          "description": "Return entities that match the specified status. Use a comma-separated list to specify multiple status values."
        },
        {
          "name": "recurring",
          "required": false,
          "description": "Determine whether returned entities are for recurring prices (`true`) or one-time prices (`false`)."
        },
        {
          "name": "billing_cycle.interval",
          "required": false,
          "description": "Return entities where the price billing cycle interval matches this value."
        },
        {
          "name": "billing_cycle.frequency",
          "required": false,
          "description": "Return entities where the price billing cycle frequency matches this value."
        },
        {
          "name": "type",
          "required": false,
          "description": "Return items that match the specified type."
        }
      ],
      "header_params": [
        {
          "name": "Skip-Count",
          "required": false,
          "description": "Set to `true` to skip the count query on list operations. When set, `meta.pagination.estimated_total` returns `-1` instead of an exact count."
        }
      ],
      "body_supported": false,
      "body_required": false,
      "body_required_keys": [],
      "permissions": [
        "price.read"
      ],
      "docs_url": "https://developer.paddle.com/api-reference/prices/list-prices"
    },
    {
      "name": "create_price",
      "label": "Create a price",
      "category": "Prices",
      "description": "Creates a new price. Prices describe how you charge for products. You must include a `product_id` in your request to relate this price to a product. If you omit the `quantity` object, Paddle automatically sets a minimum of `1` and a maximum of `100` for you. This means the most units that a customer",
      "method": "POST",
      "path": "/prices",
      "path_params": [],
      "query_params": [],
      "header_params": [],
      "body_supported": true,
      "body_required": true,
      "body_required_keys": [
        "description",
        "product_id",
        "unit_price"
      ],
      "permissions": [
        "price.write"
      ],
      "docs_url": "https://developer.paddle.com/api-reference/prices/create-price"
    },
    {
      "name": "get_price",
      "label": "Get a price",
      "category": "Prices",
      "description": "Returns a price using its ID. Use the `include` parameter to include the related product entity in the response.",
      "method": "GET",
      "path": "/prices/{price_id}",
      "path_params": [
        {
          "name": "price_id",
          "required": true,
          "description": "Paddle ID of the price entity to work with."
        }
      ],
      "query_params": [
        {
          "name": "include",
          "required": false,
          "description": "Include related entities in the response."
        }
      ],
      "header_params": [],
      "body_supported": false,
      "body_required": false,
      "body_required_keys": [],
      "permissions": [
        "price.read"
      ],
      "docs_url": "https://developer.paddle.com/api-reference/prices/get-price"
    },
    {
      "name": "update_price",
      "label": "Update a price",
      "category": "Prices",
      "description": "Updates a price using its ID. If successful, your response includes a copy of the updated price entity.",
      "method": "PATCH",
      "path": "/prices/{price_id}",
      "path_params": [
        {
          "name": "price_id",
          "required": true,
          "description": "Paddle ID of the price entity to work with."
        }
      ],
      "query_params": [],
      "header_params": [],
      "body_supported": true,
      "body_required": true,
      "body_required_keys": [],
      "permissions": [
        "price.write"
      ],
      "docs_url": "https://developer.paddle.com/api-reference/prices/update-price"
    },
    {
      "name": "preview_prices",
      "label": "Preview prices",
      "category": "Pricing preview",
      "description": "Previews calculations for one or more prices. Typically used for building pricing pages. You can provide location information when previewing prices. You must provide this if you want Paddle to calculate tax or [automatically localize prices](https://developer.paddle.com/build/products/offer-localiz",
      "method": "POST",
      "path": "/pricing-preview",
      "path_params": [],
      "query_params": [],
      "header_params": [],
      "body_supported": true,
      "body_required": true,
      "body_required_keys": [
        "items"
      ],
      "permissions": [
        "transaction.read"
      ],
      "docs_url": "https://developer.paddle.com/api-reference/pricing-preview/preview-prices"
    },
    {
      "name": "list_products",
      "label": "List products",
      "category": "Products",
      "description": "Returns a paginated list of products. Use the query parameters to page through results. By default, Paddle returns products that are `active`. Use the `status` query parameter to return products that are archived. Use the `include` parameter to include related price entities in the response.",
      "method": "GET",
      "path": "/products",
      "path_params": [],
      "query_params": [
        {
          "name": "id",
          "required": false,
          "description": "Return only the IDs specified. Use a comma-separated list to get multiple entities."
        },
        {
          "name": "after",
          "required": false,
          "description": "Return entities after the specified Paddle ID when working with paginated endpoints. Used in the `meta.pagination.next` URL in responses for list operations."
        },
        {
          "name": "per_page",
          "required": false,
          "description": "Set how many entities are returned per page. Paddle returns the maximum number of results if a number greater than the maximum is requested. Check `meta.pagination.per_page` in the response to see how many were returned. Default: `50`; Maximum: `200`."
        },
        {
          "name": "include",
          "required": false,
          "description": "Include related entities in the response. Use a comma-separated list to specify multiple entities."
        },
        {
          "name": "order_by",
          "required": false,
          "description": "Order returned entities by the specified field and direction (`[ASC]` or `[DESC]`). For example, `?order_by=id[ASC]`. Valid fields for ordering: `created_at`, `custom_data`, `description`, `id`, `image_url`, `name`, `status`, `tax_category`, and `updated_at`."
        },
        {
          "name": "status",
          "required": false,
          "description": "Return entities that match the specified status. Use a comma-separated list to specify multiple status values."
        },
        {
          "name": "tax_category",
          "required": false,
          "description": "Return entities that match the specified tax category. Use a comma-separated list to specify multiple tax categories."
        },
        {
          "name": "type",
          "required": false,
          "description": "Return items that match the specified type."
        }
      ],
      "header_params": [
        {
          "name": "Skip-Count",
          "required": false,
          "description": "Set to `true` to skip the count query on list operations. When set, `meta.pagination.estimated_total` returns `-1` instead of an exact count."
        }
      ],
      "body_supported": false,
      "body_required": false,
      "body_required_keys": [],
      "permissions": [
        "product.read"
      ],
      "docs_url": "https://developer.paddle.com/api-reference/products/list-products"
    },
    {
      "name": "create_product",
      "label": "Create a product",
      "category": "Products",
      "description": "Creates a new product. Paddle does not upload product images to a CDN. For `image_url`, you should host images on an HTTPS server that's publicly accessible. We recommend using square images (`1:1` ratio). If successful, your response includes a copy of the new product entity.",
      "method": "POST",
      "path": "/products",
      "path_params": [],
      "query_params": [],
      "header_params": [],
      "body_supported": true,
      "body_required": true,
      "body_required_keys": [
        "name",
        "tax_category"
      ],
      "permissions": [
        "product.write"
      ],
      "docs_url": "https://developer.paddle.com/api-reference/products/create-product"
    },
    {
      "name": "get_product",
      "label": "Get a product",
      "category": "Products",
      "description": "Returns a product using its ID. Use the `include` parameter to include related price entities in the response.",
      "method": "GET",
      "path": "/products/{product_id}",
      "path_params": [
        {
          "name": "product_id",
          "required": true,
          "description": "Paddle ID of the product entity to work with."
        }
      ],
      "query_params": [
        {
          "name": "include",
          "required": false,
          "description": "Include related entities in the response. Use a comma-separated list to specify multiple entities."
        }
      ],
      "header_params": [],
      "body_supported": false,
      "body_required": false,
      "body_required_keys": [],
      "permissions": [
        "product.read"
      ],
      "docs_url": "https://developer.paddle.com/api-reference/products/get-product"
    },
    {
      "name": "update_product",
      "label": "Update a product",
      "category": "Products",
      "description": "Updates a product using its ID. Paddle does not upload product images to a CDN. For `image_url`, you should host images on an HTTPS server that's publicly accessible. We recommend using square images (`1:1` ratio). If successful, your response includes a copy of the updated product entity.",
      "method": "PATCH",
      "path": "/products/{product_id}",
      "path_params": [
        {
          "name": "product_id",
          "required": true,
          "description": "Paddle ID of the product entity to work with."
        }
      ],
      "query_params": [],
      "header_params": [],
      "body_supported": true,
      "body_required": true,
      "body_required_keys": [],
      "permissions": [
        "product.write"
      ],
      "docs_url": "https://developer.paddle.com/api-reference/products/update-product"
    },
    {
      "name": "list_reports",
      "label": "List reports",
      "category": "Reports",
      "description": "Returns a paginated list of reports. Use the query parameters to page through results. By default, Paddle returns reports that are `pending` or `ready`. Use the `status` query parameter to return reports that are `failed`, `expired`, or `deleted`.",
      "method": "GET",
      "path": "/reports",
      "path_params": [],
      "query_params": [
        {
          "name": "after",
          "required": false,
          "description": "Return entities after the specified Paddle ID when working with paginated endpoints. Used in the `meta.pagination.next` URL in responses for list operations."
        },
        {
          "name": "per_page",
          "required": false,
          "description": "Set how many entities are returned per page. Paddle returns the maximum number of results if a number greater than the maximum is requested. Check `meta.pagination.per_page` in the response to see how many were returned. Default: `50`; Maximum: `200`."
        },
        {
          "name": "order_by",
          "required": false,
          "description": "Order returned entities by the specified field and direction (`[ASC]` or `[DESC]`). For example, `?order_by=id[ASC]`. Valid fields for ordering: `id`."
        },
        {
          "name": "status",
          "required": false,
          "description": "Return entities that match the specified status. Use a comma-separated list to specify multiple status values."
        }
      ],
      "header_params": [
        {
          "name": "Skip-Count",
          "required": false,
          "description": "Set to `true` to skip the count query on list operations. When set, `meta.pagination.estimated_total` returns `-1` instead of an exact count."
        }
      ],
      "body_supported": false,
      "body_required": false,
      "body_required_keys": [],
      "permissions": [
        "report.read"
      ],
      "docs_url": "https://developer.paddle.com/api-reference/reports/list-reports"
    },
    {
      "name": "create_report",
      "label": "Create a report",
      "category": "Reports",
      "description": "Creates a new report. Reports are created as `pending` initially while Paddle generates your report. They move to `ready` when they're ready to download. You can download a report when it's ready using the [get a CSV file for a report operation](https://developer.paddle.com/api-reference/reports/get",
      "method": "POST",
      "path": "/reports",
      "path_params": [],
      "query_params": [],
      "header_params": [],
      "body_supported": true,
      "body_required": true,
      "body_required_keys": [
        "type"
      ],
      "permissions": [
        "report.write"
      ],
      "docs_url": "https://developer.paddle.com/api-reference/reports/create-report"
    },
    {
      "name": "get_report",
      "label": "Get a report",
      "category": "Reports",
      "description": "Returns a report using its ID.",
      "method": "GET",
      "path": "/reports/{report_id}",
      "path_params": [
        {
          "name": "report_id",
          "required": true,
          "description": "Paddle ID of the report entity."
        }
      ],
      "query_params": [],
      "header_params": [],
      "body_supported": false,
      "body_required": false,
      "body_required_keys": [],
      "permissions": [
        "report.read"
      ],
      "docs_url": "https://developer.paddle.com/api-reference/reports/get-report"
    },
    {
      "name": "get_report_csv",
      "label": "Get a CSV file for a report",
      "category": "Reports",
      "description": "Returns a link to a CSV file for a report. Only returned for reports that are `ready`. This means Paddle has completed processing the report and it's ready to download. The link returned is not a permanent link. It expires after 3 minutes.",
      "method": "GET",
      "path": "/reports/{report_id}/download-url",
      "path_params": [
        {
          "name": "report_id",
          "required": true,
          "description": "Paddle ID of the report entity."
        }
      ],
      "query_params": [],
      "header_params": [],
      "body_supported": false,
      "body_required": false,
      "body_required_keys": [],
      "permissions": [
        "report.read"
      ],
      "docs_url": "https://developer.paddle.com/api-reference/reports/get-report-csv"
    },
    {
      "name": "list_simulation_types",
      "label": "List simulation types",
      "category": "Simulation types",
      "description": "Returns a list of simulation types (events and scenarios) that you can choose from when creating simulations.",
      "method": "GET",
      "path": "/simulation-types",
      "path_params": [],
      "query_params": [],
      "header_params": [],
      "body_supported": false,
      "body_required": false,
      "body_required_keys": [],
      "permissions": [],
      "docs_url": "https://developer.paddle.com/api-reference/simulation-types/list-simulation-types"
    },
    {
      "name": "list_simulations",
      "label": "List simulations",
      "category": "Simulations",
      "description": "Returns a paginated list of simulations. Use the query parameters to [page through results](https://developer.paddle.com/api-reference/about/pagination).",
      "method": "GET",
      "path": "/simulations",
      "path_params": [],
      "query_params": [
        {
          "name": "id",
          "required": false,
          "description": "Return only the IDs specified. Use a comma-separated list to get multiple entities."
        },
        {
          "name": "after",
          "required": false,
          "description": "Return entities after the specified Paddle ID when working with paginated endpoints. Used in the `meta.pagination.next` URL in responses for list operations."
        },
        {
          "name": "per_page",
          "required": false,
          "description": "Set how many entities are returned per page. Paddle returns the maximum number of results if a number greater than the maximum is requested. Check `meta.pagination.per_page` in the response to see how many were returned. Default: `50`; Maximum: `200`."
        },
        {
          "name": "notification_setting_id",
          "required": false,
          "description": "Return entities related to the specified notification destination. Use a comma-separated list to specify multiple notification destination IDs."
        },
        {
          "name": "order_by",
          "required": false,
          "description": "Order returned entities by the specified field and direction (`[ASC]` or `[DESC]`). For example, `?order_by=id[ASC]`. Valid fields for ordering: `id`."
        },
        {
          "name": "status",
          "required": false,
          "description": "Return entities that match the specified status. Use a comma-separated list to specify multiple status values."
        }
      ],
      "header_params": [
        {
          "name": "Skip-Count",
          "required": false,
          "description": "Set to `true` to skip the count query on list operations. When set, `meta.pagination.estimated_total` returns `-1` instead of an exact count."
        }
      ],
      "body_supported": false,
      "body_required": false,
      "body_required_keys": [],
      "permissions": [
        "notification_simulation.read"
      ],
      "docs_url": "https://developer.paddle.com/api-reference/simulations/list-simulations"
    },
    {
      "name": "create_simulation",
      "label": "Create a simulation",
      "category": "Simulations",
      "description": "Creates a new simulation for a notification setting (notification destination). simulated webhook payloads with real data. The API key making the request needs read permissions: * For the entities you provided, or the request fails. * For related entities which aren't nested in the entities you prov",
      "method": "POST",
      "path": "/simulations",
      "path_params": [],
      "query_params": [],
      "header_params": [],
      "body_supported": true,
      "body_required": true,
      "body_required_keys": [
        "name",
        "notification_setting_id",
        "type"
      ],
      "permissions": [
        "notification_simulation.write"
      ],
      "docs_url": "https://developer.paddle.com/api-reference/simulations/create-simulation"
    },
    {
      "name": "get_simulation",
      "label": "Get a simulation",
      "category": "Simulations",
      "description": "Returns a simulation using its ID.",
      "method": "GET",
      "path": "/simulations/{simulation_id}",
      "path_params": [
        {
          "name": "simulation_id",
          "required": true,
          "description": "Paddle ID of the simulation entity to work with."
        }
      ],
      "query_params": [],
      "header_params": [],
      "body_supported": false,
      "body_required": false,
      "body_required_keys": [],
      "permissions": [
        "notification_simulation.read"
      ],
      "docs_url": "https://developer.paddle.com/api-reference/simulations/get-simulation"
    },
    {
      "name": "update_simulation",
      "label": "Update a simulation",
      "category": "Simulations",
      "description": "Updates a simulation using its ID. For scenario simulations, you can optionally include a `config.entities` object in the request body with entity IDs to populate simulated webhook payloads with real data. The API key making the request needs read permissions: * For the entities you provided, or the",
      "method": "PATCH",
      "path": "/simulations/{simulation_id}",
      "path_params": [
        {
          "name": "simulation_id",
          "required": true,
          "description": "Paddle ID of the simulation entity to work with."
        }
      ],
      "query_params": [],
      "header_params": [],
      "body_supported": true,
      "body_required": true,
      "body_required_keys": [],
      "permissions": [
        "notification_simulation.write"
      ],
      "docs_url": "https://developer.paddle.com/api-reference/simulations/update-simulation"
    },
    {
      "name": "list_simulation_runs",
      "label": "List runs for a simulation",
      "category": "Simulation runs",
      "description": "Returns a paginated list of simulation runs. Use the query parameters to [page through results](https://developer.paddle.com/api-reference/about/pagination). Use the `include` parameter to [include related entities](https://developer.paddle.com/api-reference/about/include-entities) in the response.",
      "method": "GET",
      "path": "/simulations/{simulation_id}/runs",
      "path_params": [
        {
          "name": "simulation_id",
          "required": true,
          "description": "Paddle ID of the simulation entity to work with."
        }
      ],
      "query_params": [
        {
          "name": "id",
          "required": false,
          "description": "Return only the IDs specified. Use a comma-separated list to get multiple entities."
        },
        {
          "name": "after",
          "required": false,
          "description": "Return entities after the specified Paddle ID when working with paginated endpoints. Used in the `meta.pagination.next` URL in responses for list operations."
        },
        {
          "name": "per_page",
          "required": false,
          "description": "Set how many entities are returned per page. Paddle returns the maximum number of results if a number greater than the maximum is requested. Check `meta.pagination.per_page` in the response to see how many were returned. Default: `50`; Maximum: `200`."
        },
        {
          "name": "include",
          "required": false,
          "description": "Include related entities in the response."
        },
        {
          "name": "order_by",
          "required": false,
          "description": "Order returned entities by the specified field and direction (`[ASC]` or `[DESC]`). For example, `?order_by=id[ASC]`. Valid fields for ordering: `id`."
        }
      ],
      "header_params": [
        {
          "name": "Skip-Count",
          "required": false,
          "description": "Set to `true` to skip the count query on list operations. When set, `meta.pagination.estimated_total` returns `-1` instead of an exact count."
        }
      ],
      "body_supported": false,
      "body_required": false,
      "body_required_keys": [],
      "permissions": [
        "notification_simulation.read"
      ],
      "docs_url": "https://developer.paddle.com/api-reference/simulation-runs/list-simulation-runs"
    },
    {
      "name": "create_simulation_run",
      "label": "Create a run for a simulation",
      "category": "Simulation runs",
      "description": "Creates a new simulation run for a simulation. If successful, your response includes a copy of the new simulation run entity.",
      "method": "POST",
      "path": "/simulations/{simulation_id}/runs",
      "path_params": [
        {
          "name": "simulation_id",
          "required": true,
          "description": "Paddle ID of the simulation entity to work with."
        }
      ],
      "query_params": [],
      "header_params": [],
      "body_supported": false,
      "body_required": false,
      "body_required_keys": [],
      "permissions": [
        "notification_simulation.write"
      ],
      "docs_url": "https://developer.paddle.com/api-reference/simulation-runs/create-simulation-run"
    },
    {
      "name": "get_simulation_run",
      "label": "Get a run for a simulation",
      "category": "Simulation runs",
      "description": "Returns a simulation run using its ID. Use the `include` parameter to include related entities in the response.",
      "method": "GET",
      "path": "/simulations/{simulation_id}/runs/{simulation_run_id}",
      "path_params": [
        {
          "name": "simulation_id",
          "required": true,
          "description": "Paddle ID of the simulation entity to work with."
        },
        {
          "name": "simulation_run_id",
          "required": true,
          "description": "Paddle ID of the simulation run entity to work with."
        }
      ],
      "query_params": [
        {
          "name": "include",
          "required": false,
          "description": "Include related entities in the response."
        }
      ],
      "header_params": [],
      "body_supported": false,
      "body_required": false,
      "body_required_keys": [],
      "permissions": [
        "notification_simulation.read"
      ],
      "docs_url": "https://developer.paddle.com/api-reference/simulation-runs/get-simulation-run"
    },
    {
      "name": "list_simulations_events",
      "label": "List events for a simulation run",
      "category": "Simulation run events",
      "description": "Returns a paginated list of simulations. Use the query parameters to [page through results](https://developer.paddle.com/api-reference/about/pagination).",
      "method": "GET",
      "path": "/simulations/{simulation_id}/runs/{simulation_run_id}/events",
      "path_params": [
        {
          "name": "simulation_id",
          "required": true,
          "description": "Paddle ID of the simulation entity to work with."
        },
        {
          "name": "simulation_run_id",
          "required": true,
          "description": "Paddle ID of the simulation run entity to work with."
        }
      ],
      "query_params": [
        {
          "name": "id",
          "required": false,
          "description": "Return only the IDs specified. Use a comma-separated list to get multiple entities."
        },
        {
          "name": "after",
          "required": false,
          "description": "Return entities after the specified Paddle ID when working with paginated endpoints. Used in the `meta.pagination.next` URL in responses for list operations."
        },
        {
          "name": "per_page",
          "required": false,
          "description": "Set how many entities are returned per page. Paddle returns the maximum number of results if a number greater than the maximum is requested. Check `meta.pagination.per_page` in the response to see how many were returned. Default: `50`; Maximum: `200`."
        },
        {
          "name": "order_by",
          "required": false,
          "description": "Order returned entities by the specified field and direction (`[ASC]` or `[DESC]`). For example, `?order_by=id[ASC]`. Valid fields for ordering: `id`."
        }
      ],
      "header_params": [
        {
          "name": "Skip-Count",
          "required": false,
          "description": "Set to `true` to skip the count query on list operations. When set, `meta.pagination.estimated_total` returns `-1` instead of an exact count."
        }
      ],
      "body_supported": false,
      "body_required": false,
      "body_required_keys": [],
      "permissions": [
        "notification_simulation.read"
      ],
      "docs_url": "https://developer.paddle.com/api-reference/simulation-events/list-simulation-events"
    },
    {
      "name": "get_simulation_event",
      "label": "Get an event for a simulation run",
      "category": "Simulation run events",
      "description": "Returns a simulation event using its ID.",
      "method": "GET",
      "path": "/simulations/{simulation_id}/runs/{simulation_run_id}/events/{simulation_event_id}",
      "path_params": [
        {
          "name": "simulation_id",
          "required": true,
          "description": "Paddle ID of the simulation entity to work with."
        },
        {
          "name": "simulation_run_id",
          "required": true,
          "description": "Paddle ID of the simulation run entity to work with."
        },
        {
          "name": "simulation_event_id",
          "required": true,
          "description": "Paddle ID of the simulation event entity to work with."
        }
      ],
      "query_params": [],
      "header_params": [],
      "body_supported": false,
      "body_required": false,
      "body_required_keys": [],
      "permissions": [
        "notification_simulation.read"
      ],
      "docs_url": "https://developer.paddle.com/api-reference/simulation-events/get-simulation-event"
    },
    {
      "name": "replay_simulation_run_event",
      "label": "Replay an event for a simulation run",
      "category": "Simulation run events",
      "description": "Attempts to resend a simulation run log using its ID. Paddle creates a new simulation run log entity for the replay, related to the same simulation run. If successful, your response includes the new simulation run log entity.",
      "method": "POST",
      "path": "/simulations/{simulation_id}/runs/{simulation_run_id}/events/{simulation_event_id}/replay",
      "path_params": [
        {
          "name": "simulation_id",
          "required": true,
          "description": "Paddle ID of the simulation entity to work with."
        },
        {
          "name": "simulation_run_id",
          "required": true,
          "description": "Paddle ID of the simulation run entity to work with."
        },
        {
          "name": "simulation_event_id",
          "required": true,
          "description": "Paddle ID of the simulation event entity to work with."
        }
      ],
      "query_params": [],
      "header_params": [],
      "body_supported": false,
      "body_required": false,
      "body_required_keys": [],
      "permissions": [
        "notification_simulation.write"
      ],
      "docs_url": "https://developer.paddle.com/api-reference/simulation-events/replay-simulation-run-event"
    },
    {
      "name": "list_subscription_history",
      "label": "List history for a subscription",
      "category": "Subscription history",
      "description": "Returns a paginated list of history entries for a subscription. Use the query parameters to filter and page through results. Subscription history records the changes made to a subscription over its lifetime, so you can see what changed, when it happened, where it originated, and who made the change.",
      "method": "GET",
      "path": "/subscriptions/{subscription_id}/history",
      "path_params": [
        {
          "name": "subscription_id",
          "required": true,
          "description": ""
        }
      ],
      "query_params": [
        {
          "name": "action",
          "required": false,
          "description": "Return history entries that match the specified action. Use a comma-separated list to specify multiple action values."
        },
        {
          "name": "source",
          "required": false,
          "description": "Return history entries that match the specified source. Use a comma-separated list to specify multiple source values."
        },
        {
          "name": "actor_type",
          "required": false,
          "description": "Return history entries that match the specified actor type. Use a comma-separated list to specify multiple actor type values."
        },
        {
          "name": "actor_id",
          "required": false,
          "description": "Return history entries that match the specified actor ID. Use a comma-separated list to specify multiple actor ID values. Only applicable if `actor_type` is also selected."
        },
        {
          "name": "reason",
          "required": false,
          "description": "Return history entries that match the specified reason. Use a comma-separated list to specify multiple reason values."
        },
        {
          "name": "occurred_at",
          "required": false,
          "description": "Return entities that occurred at a specific time. Use `[LTE]` (less than or equal to) or `[GTE]` (greater than or equal to) operators with an RFC 3339 datetime string. For example, `occurred_at[LTE]=2023-04-18T17:03:26` or `occurred_at[GTE]=2023-04-18T17:03:26`."
        },
        {
          "name": "after",
          "required": false,
          "description": "Return entities after the specified Paddle ID when working with paginated endpoints. Used in the `meta.pagination.next` URL in responses for list operations."
        },
        {
          "name": "per_page",
          "required": false,
          "description": "Set how many entities are returned per page. Paddle returns the maximum number of results if a number greater than the maximum is requested. Check `meta.pagination.per_page` in the response to see how many were returned. Default: `50`; Maximum: `200`."
        },
        {
          "name": "order_by",
          "required": false,
          "description": "Order returned entities by the specified field and direction (`[ASC]` or `[DESC]`). For example, `?order_by=occurred_at[DESC]`. Valid fields for ordering: `occurred_at`."
        }
      ],
      "header_params": [
        {
          "name": "Skip-Count",
          "required": false,
          "description": "Set to `true` to skip the count query on list operations. When set, `meta.pagination.estimated_total` returns `-1` instead of an exact count."
        }
      ],
      "body_supported": false,
      "body_required": false,
      "body_required_keys": [],
      "permissions": [
        "subscription_history.read"
      ],
      "docs_url": "https://developer.paddle.com/api-reference/subscription-history/list-subscription-history"
    },
    {
      "name": "list_subscriptions",
      "label": "List subscriptions",
      "category": "Subscriptions",
      "description": "Returns a paginated list of subscriptions. Use the query parameters to page through results.",
      "method": "GET",
      "path": "/subscriptions",
      "path_params": [],
      "query_params": [
        {
          "name": "id",
          "required": false,
          "description": "Return only the IDs specified. Use a comma-separated list to get multiple entities."
        },
        {
          "name": "after",
          "required": false,
          "description": "Return entities after the specified Paddle ID when working with paginated endpoints. Used in the `meta.pagination.next` URL in responses for list operations."
        },
        {
          "name": "per_page",
          "required": false,
          "description": "Set how many entities are returned per page. Paddle returns the maximum number of results if a number greater than the maximum is requested. Check `meta.pagination.per_page` in the response to see how many were returned. Default: `50`; Maximum: `200`."
        },
        {
          "name": "address_id",
          "required": false,
          "description": "Return entities related to the specified address. Use a comma-separated list to specify multiple address IDs."
        },
        {
          "name": "collection_mode",
          "required": false,
          "description": "Return entities that match the specified collection mode."
        },
        {
          "name": "customer_id",
          "required": false,
          "description": "Return entities related to the specified customer. Use a comma-separated list to specify multiple customer IDs."
        },
        {
          "name": "order_by",
          "required": false,
          "description": "Order returned entities by the specified field and direction (`[ASC]` or `[DESC]`). For example, `?order_by=id[ASC]`. Valid fields for ordering: `id`."
        },
        {
          "name": "price_id",
          "required": false,
          "description": "Return entities related to the specified price. Use a comma-separated list to specify multiple price IDs."
        },
        {
          "name": "scheduled_change_action",
          "required": false,
          "description": "Return subscriptions that have a scheduled change. Use a comma-separated list to specify multiple scheduled change actions."
        },
        {
          "name": "next_billed_at",
          "required": false,
          "description": "Return entities next billed at a specific time. Pass `null` to return entities with no next billing date."
        },
        {
          "name": "status",
          "required": false,
          "description": "Return entities that match the specified status. Use a comma-separated list to specify multiple status values."
        }
      ],
      "header_params": [
        {
          "name": "Skip-Count",
          "required": false,
          "description": "Set to `true` to skip the count query on list operations. When set, `meta.pagination.estimated_total` returns `-1` instead of an exact count."
        }
      ],
      "body_supported": false,
      "body_required": false,
      "body_required_keys": [],
      "permissions": [
        "subscription.read"
      ],
      "docs_url": "https://developer.paddle.com/api-reference/subscriptions/list-subscriptions"
    },
    {
      "name": "get_subscription",
      "label": "Get a subscription",
      "category": "Subscriptions",
      "description": "Returns a subscription using its ID. Use the `include` parameter to include transaction information in the response.",
      "method": "GET",
      "path": "/subscriptions/{subscription_id}",
      "path_params": [
        {
          "name": "subscription_id",
          "required": true,
          "description": "Paddle ID of the subscription entity to work with."
        }
      ],
      "query_params": [
        {
          "name": "include",
          "required": false,
          "description": "Include related entities in the response. Use a comma-separated list to specify multiple entities."
        }
      ],
      "header_params": [],
      "body_supported": false,
      "body_required": false,
      "body_required_keys": [],
      "permissions": [
        "subscription.read"
      ],
      "docs_url": "https://developer.paddle.com/api-reference/subscriptions/get-subscription"
    },
    {
      "name": "update_subscription",
      "label": "Update a subscription",
      "category": "Subscriptions",
      "description": "Updates a subscription using its ID. When making changes to items or the next billing date for a subscription, you must include the `proration_billing_mode` field to tell Paddle how to bill for those changes. Send the complete list of items that you'd like to be on a subscription — including existin",
      "method": "PATCH",
      "path": "/subscriptions/{subscription_id}",
      "path_params": [
        {
          "name": "subscription_id",
          "required": true,
          "description": "Paddle ID of the subscription entity to work with."
        }
      ],
      "query_params": [],
      "header_params": [],
      "body_supported": true,
      "body_required": true,
      "body_required_keys": [],
      "permissions": [
        "subscription.write"
      ],
      "docs_url": "https://developer.paddle.com/api-reference/subscriptions/update-subscription"
    },
    {
      "name": "cancel_subscription",
      "label": "Cancel a subscription",
      "category": "Subscriptions",
      "description": "Cancels a subscription using its ID. By default, active subscriptions are canceled at the end of the billing period. When you send a request to cancel, Paddle creates a `scheduled_change` against the subscription entity to say that it should cancel at the end of the current billing period. Its `stat",
      "method": "POST",
      "path": "/subscriptions/{subscription_id}/cancel",
      "path_params": [
        {
          "name": "subscription_id",
          "required": true,
          "description": "Paddle ID of the subscription entity to work with."
        }
      ],
      "query_params": [],
      "header_params": [],
      "body_supported": true,
      "body_required": true,
      "body_required_keys": [],
      "permissions": [
        "subscription.write"
      ],
      "docs_url": "https://developer.paddle.com/api-reference/subscriptions/cancel-subscription"
    },
    {
      "name": "pause_subscription",
      "label": "Pause a subscription",
      "category": "Subscriptions",
      "description": "Pauses a subscription using its ID. By default, subscriptions are paused at the end of the billing period. When you send a request to pause, Paddle creates a `scheduled_change` against the subscription entity to say that it should pause at the end of the current billing period. Its `status` remains ",
      "method": "POST",
      "path": "/subscriptions/{subscription_id}/pause",
      "path_params": [
        {
          "name": "subscription_id",
          "required": true,
          "description": "Paddle ID of the subscription entity to work with."
        }
      ],
      "query_params": [],
      "header_params": [],
      "body_supported": true,
      "body_required": true,
      "body_required_keys": [],
      "permissions": [
        "subscription.write"
      ],
      "docs_url": "https://developer.paddle.com/api-reference/subscriptions/pause-subscription"
    },
    {
      "name": "resume_subscription",
      "label": "Resume a paused subscription",
      "category": "Subscriptions",
      "description": "Resumes a paused subscription using its ID. Only `paused` subscriptions can be resumed. If an `active` subscription has a scheduled change to pause in the future, use this operation to set or change the resume date. You can't resume a `canceled` subscription. On resume, Paddle bills for a subscripti",
      "method": "POST",
      "path": "/subscriptions/{subscription_id}/resume",
      "path_params": [
        {
          "name": "subscription_id",
          "required": true,
          "description": "Paddle ID of the subscription entity to work with."
        }
      ],
      "query_params": [],
      "header_params": [],
      "body_supported": true,
      "body_required": true,
      "body_required_keys": [],
      "permissions": [
        "subscription.write"
      ],
      "docs_url": "https://developer.paddle.com/api-reference/subscriptions/resume-subscription"
    },
    {
      "name": "activate_subscription",
      "label": "Activate a trialing subscription",
      "category": "Subscriptions",
      "description": "Activates a trialing subscription using its ID. Only automatically-collected subscriptions where the status is `trialing` can be activated. On activation, Paddle bills for a subscription immediately. Subscription billing dates are recalculated based on the activation date (the time the activation re",
      "method": "POST",
      "path": "/subscriptions/{subscription_id}/activate",
      "path_params": [
        {
          "name": "subscription_id",
          "required": true,
          "description": "Paddle ID of the subscription entity to work with."
        }
      ],
      "query_params": [],
      "header_params": [],
      "body_supported": false,
      "body_required": false,
      "body_required_keys": [],
      "permissions": [
        "subscription.write"
      ],
      "docs_url": "https://developer.paddle.com/api-reference/subscriptions/activate-subscription"
    },
    {
      "name": "get_subscription_update_payment_method_transaction",
      "label": "Get a transaction to update payment method",
      "category": "Subscriptions",
      "description": "Returns a transaction that you can pass to a checkout to let customers update their payment details. Only for subscriptions where `collection_mode` is `automatic`. The transaction returned depends on the status of the related subscription: * Where a subscription is `past_due`, it returns the most re",
      "method": "GET",
      "path": "/subscriptions/{subscription_id}/update-payment-method-transaction",
      "path_params": [
        {
          "name": "subscription_id",
          "required": true,
          "description": "Paddle ID of the subscription entity to work with."
        }
      ],
      "query_params": [],
      "header_params": [],
      "body_supported": false,
      "body_required": false,
      "body_required_keys": [],
      "permissions": [
        "transaction.write"
      ],
      "docs_url": "https://developer.paddle.com/api-reference/subscriptions/update-payment-method"
    },
    {
      "name": "preview_subscription_update",
      "label": "Preview an update to a subscription",
      "category": "Subscriptions",
      "description": "Previews an update for a subscription without applying those changes. Typically used for previewing proration before making changes to a subscription. If successful, your response includes `immediate_transaction`, `next_transaction`, and `recurring_transaction_details` so you can see expected transa",
      "method": "PATCH",
      "path": "/subscriptions/{subscription_id}/preview",
      "path_params": [
        {
          "name": "subscription_id",
          "required": true,
          "description": "Paddle ID of the subscription entity to work with."
        }
      ],
      "query_params": [],
      "header_params": [],
      "body_supported": true,
      "body_required": true,
      "body_required_keys": [],
      "permissions": [
        "subscription.read"
      ],
      "docs_url": "https://developer.paddle.com/api-reference/subscriptions/preview-subscription"
    },
    {
      "name": "create_subscription_charge",
      "label": "Create a one-time charge for a subscription",
      "category": "Subscriptions",
      "description": "Creates a new one-time charge for a subscription. Use to bill non-recurring items to a subscription. Non-recurring items are price entities where the `billing_cycle` is `null`. If successful, Paddle responds with the updated subscription entity. However, one-time charges aren't held against the subs",
      "method": "POST",
      "path": "/subscriptions/{subscription_id}/charge",
      "path_params": [
        {
          "name": "subscription_id",
          "required": true,
          "description": "Paddle ID of the subscription entity to work with."
        }
      ],
      "query_params": [],
      "header_params": [],
      "body_supported": true,
      "body_required": true,
      "body_required_keys": [
        "effective_from",
        "items"
      ],
      "permissions": [
        "subscription.write"
      ],
      "docs_url": "https://developer.paddle.com/api-reference/subscriptions/create-one-time-charge"
    },
    {
      "name": "preview_subscription_charge",
      "label": "Preview a one-time charge for a subscription",
      "category": "Subscriptions",
      "description": "Previews creating a one-time charge for a subscription without billing that charge. Typically used for previewing calculations before making changes to a subscription. One-time charges are non-recurring items. These are price entities where the `billing_cycle` is `null`. If successful, your response",
      "method": "POST",
      "path": "/subscriptions/{subscription_id}/charge/preview",
      "path_params": [
        {
          "name": "subscription_id",
          "required": true,
          "description": "Paddle ID of the subscription entity to work with."
        }
      ],
      "query_params": [],
      "header_params": [],
      "body_supported": true,
      "body_required": true,
      "body_required_keys": [
        "effective_from",
        "items"
      ],
      "permissions": [
        "subscription.read"
      ],
      "docs_url": "https://developer.paddle.com/api-reference/subscriptions/preview-subscription-charge"
    },
    {
      "name": "list_transactions",
      "label": "List transactions",
      "category": "Transactions",
      "description": "Returns a paginated list of transactions. Use the query parameters to page through results. Use the `include` parameter to include related entities in the response.",
      "method": "GET",
      "path": "/transactions",
      "path_params": [],
      "query_params": [
        {
          "name": "include",
          "required": false,
          "description": "Include related entities in the response. Use a comma-separated list to specify multiple entities."
        },
        {
          "name": "id",
          "required": false,
          "description": "Return only the IDs specified. Use a comma-separated list to get multiple entities."
        },
        {
          "name": "after",
          "required": false,
          "description": "Return entities after the specified Paddle ID when working with paginated endpoints. Used in the `meta.pagination.next` URL in responses for list operations."
        },
        {
          "name": "billed_at",
          "required": false,
          "description": "Return entities billed at a specific time. Pass an RFC 3339 datetime string, or use `[LT]` (less than), `[LTE]` (less than or equal to), `[GT]` (greater than), or `[GTE]` (greater than or equal to) operators. For example, `billed_at=2023-04-18T17:03:26` or `billed_at[LT]=2023-04-18T17:03:26`."
        },
        {
          "name": "collection_mode",
          "required": false,
          "description": "Return entities that match the specified collection mode."
        },
        {
          "name": "created_at",
          "required": false,
          "description": "Return entities created at a specific time. Pass an RFC 3339 datetime string, or use `[LT]` (less than), `[LTE]` (less than or equal to), `[GT]` (greater than), or `[GTE]` (greater than or equal to) operators. For example, `created_at=2023-04-18T17:03:26` or `created_at[LT]=2023-04-18T17:03:26`."
        },
        {
          "name": "customer_id",
          "required": false,
          "description": "Return entities related to the specified customer. Use a comma-separated list to specify multiple customer IDs."
        },
        {
          "name": "invoice_number",
          "required": false,
          "description": "Return entities that match the invoice number. Use a comma-separated list to specify multiple invoice numbers."
        },
        {
          "name": "origin",
          "required": false,
          "description": "Return entities related to the specified origin. Use a comma-separated list to specify multiple origins."
        },
        {
          "name": "order_by",
          "required": false,
          "description": "Order returned entities by the specified field and direction (`[ASC]` or `[DESC]`). For example, `?order_by=id[ASC]`. Valid fields for ordering: `billed_at`, `created_at`, `id`, and `updated_at`."
        },
        {
          "name": "status",
          "required": false,
          "description": "Return entities that match the specified status. Use a comma-separated list to specify multiple status values."
        },
        {
          "name": "subscription_id",
          "required": false,
          "description": "Return entities related to the specified subscription. Use a comma-separated list to specify multiple subscription IDs. Pass `null` to return entities that aren't related to any subscription."
        },
        {
          "name": "per_page",
          "required": false,
          "description": "Set how many entities are returned per page. Paddle returns the maximum number of results if a number greater than the maximum is requested. Check `meta.pagination.per_page` in the response to see how many were returned. Default: `30`; Maximum: `30`."
        },
        {
          "name": "updated_at",
          "required": false,
          "description": "Return entities updated at a specific time. Pass an RFC 3339 datetime string, or use `[LT]` (less than), `[LTE]` (less than or equal to), `[GT]` (greater than), or `[GTE]` (greater than or equal to) operators. For example, `updated_at=2023-04-18T17:03:26` or `updated_at[LT]=2023-04-18T17:03:26`."
        }
      ],
      "header_params": [
        {
          "name": "Skip-Count",
          "required": false,
          "description": "Set to `true` to skip the count query on list operations. When set, `meta.pagination.estimated_total` returns `-1` instead of an exact count."
        }
      ],
      "body_supported": false,
      "body_required": false,
      "body_required_keys": [],
      "permissions": [
        "transaction.read"
      ],
      "docs_url": "https://developer.paddle.com/api-reference/transactions/list-transactions"
    },
    {
      "name": "create_transaction",
      "label": "Create a transaction",
      "category": "Transactions",
      "description": "Creates a new transaction. Transactions are typically created with the status of `draft` or `ready` initially: * Draft transactions have `items` against them, but don't have all of the required fields for billing. Paddle creates draft transactions automatically when a checkout is opened. * Paddle au",
      "method": "POST",
      "path": "/transactions",
      "path_params": [],
      "query_params": [
        {
          "name": "include",
          "required": false,
          "description": "Include related entities in the response. Use a comma-separated list to specify multiple entities."
        }
      ],
      "header_params": [],
      "body_supported": true,
      "body_required": true,
      "body_required_keys": [
        "items"
      ],
      "permissions": [
        "transaction.write"
      ],
      "docs_url": "https://developer.paddle.com/api-reference/transactions/create-transaction"
    },
    {
      "name": "get_transaction",
      "label": "Get a transaction",
      "category": "Transactions",
      "description": "Returns a transaction using its ID. Use the `include` parameter to include related entities in the response.",
      "method": "GET",
      "path": "/transactions/{transaction_id}",
      "path_params": [
        {
          "name": "transaction_id",
          "required": true,
          "description": "Paddle ID of the transaction entity to work with."
        }
      ],
      "query_params": [
        {
          "name": "include",
          "required": false,
          "description": "Include related entities in the response. Use a comma-separated list to specify multiple entities."
        }
      ],
      "header_params": [],
      "body_supported": false,
      "body_required": false,
      "body_required_keys": [],
      "permissions": [
        "transaction.read"
      ],
      "docs_url": "https://developer.paddle.com/api-reference/transactions/get-transaction"
    },
    {
      "name": "update_transaction",
      "label": "Update a transaction",
      "category": "Transactions",
      "description": "Updates a transaction using its ID. You can update transactions that are `draft` or `ready`. `billed` and `completed` transactions are considered records for tax and legal purposes, so they can't be changed. You can either: * Create [an adjustment](https://developer.paddle.com/api-reference/adjustme",
      "method": "PATCH",
      "path": "/transactions/{transaction_id}",
      "path_params": [
        {
          "name": "transaction_id",
          "required": true,
          "description": "Paddle ID of the transaction entity to work with."
        }
      ],
      "query_params": [
        {
          "name": "include",
          "required": false,
          "description": "Include related entities in the response. Use a comma-separated list to specify multiple entities."
        }
      ],
      "header_params": [],
      "body_supported": true,
      "body_required": true,
      "body_required_keys": [],
      "permissions": [
        "transaction.write"
      ],
      "docs_url": "https://developer.paddle.com/api-reference/transactions/update-transaction"
    },
    {
      "name": "preview_transaction_create",
      "label": "Preview a transaction",
      "category": "Transactions",
      "description": "Previews a transaction without creating a transaction entity. Typically used for creating more advanced, dynamic pricing pages where users can build their own plans. Consider using [the preview prices operation](https://developer.paddle.com/api-reference/pricing-preview/preview-prices) for simpler p",
      "method": "POST",
      "path": "/transactions/preview",
      "path_params": [],
      "query_params": [],
      "header_params": [],
      "body_supported": true,
      "body_required": true,
      "body_required_keys": [
        "items"
      ],
      "permissions": [
        "transaction.read"
      ],
      "docs_url": "https://developer.paddle.com/api-reference/transactions/preview-transaction"
    },
    {
      "name": "revise_transaction",
      "label": "Revise customer information on a billed or completed transaction",
      "category": "Transactions",
      "description": "Revises customer information for a billed or completed transaction. Revise a transaction to rectify incorrect customer, address, or business information on invoice documents generated by Paddle. You can revise transaction details that don't impact the tax rates on a transaction. This includes: * Cus",
      "method": "POST",
      "path": "/transactions/{transaction_id}/revise",
      "path_params": [
        {
          "name": "transaction_id",
          "required": true,
          "description": "Paddle ID of the transaction entity to work with."
        }
      ],
      "query_params": [],
      "header_params": [],
      "body_supported": true,
      "body_required": true,
      "body_required_keys": [],
      "permissions": [
        "transaction.write"
      ],
      "docs_url": "https://developer.paddle.com/api-reference/transactions/revise-transaction"
    },
    {
      "name": "get_transaction_invoice",
      "label": "Get a PDF invoice for a transaction",
      "category": "Transactions",
      "description": "Returns a link to an invoice PDF for a transaction. Invoice PDFs are available for both automatically and manually-collected transactions: * The PDF for manually-collected transactions includes payment terms, purchase order number, and notes for your customer. It's a demand for payment from your cus",
      "method": "GET",
      "path": "/transactions/{transaction_id}/invoice",
      "path_params": [
        {
          "name": "transaction_id",
          "required": true,
          "description": "Paddle ID of the transaction entity to work with."
        }
      ],
      "query_params": [
        {
          "name": "disposition",
          "required": false,
          "description": "Determine whether the generated URL should download the PDF as an attachment saved locally, or open it inline in the browser. Default: `attachment`."
        }
      ],
      "header_params": [],
      "body_supported": false,
      "body_required": false,
      "body_required_keys": [],
      "permissions": [
        "transaction.read"
      ],
      "docs_url": "https://developer.paddle.com/api-reference/transactions/get-invoice-pdf"
    }
  ]
}
''')
OPERATIONS: dict[str, dict[str, Any]] = {
    row["name"]: row for row in _catalog["operations"]
}
assert len(OPERATIONS) == len(_catalog["operations"]), "Duplicate Paddle actions"
_JSON_EDITOR = {"ui:widget": "code_editor", "x-code-language": "json"}


class PaddleApiKeyCredential(BaseModel):
    """Server-side Paddle Billing API key for one environment."""

    credential_type: Literal["paddle_api_key"] = Field(
        "paddle_api_key", json_schema_extra={"ui:hidden": True}
    )
    environment: Literal["sandbox", "live"] = Field(
        "sandbox",
        title="Environment",
        description="Sandbox uses test data and never charges real money. Live uses your production Paddle account.",
    )
    api_key: str = Field(
        ...,
        title="API Key",
        description="A server-side API key from Paddle → Developer tools → Authentication. Assign the permissions needed for your actions.",
        json_schema_extra={"ui:widget": "password"},
    )

    model_config = ConfigDict(
        title="Paddle API Key",
        json_schema_extra={
            "x-credential-url": "https://developer.paddle.com/api-reference/about/authentication/",
        }
    )


def _field_name(prefix: str, raw: str) -> str:
    return prefix + "_" + re.sub(r"[^a-zA-Z0-9]+", "_", raw).strip("_").lower()


def _make_config(op: dict[str, Any]) -> type[BaseModel]:
    name = op["name"]
    permissions = ", ".join(op["permissions"])
    detail = op["description"] or op["label"]
    if permissions:
        detail += f" Required API key permission: {permissions}."
    fields: dict[str, tuple[Any, Any]] = {
        "operation": (
            Literal[name],
            Field(
                name,
                title=op["label"],
                description=detail,
                json_schema_extra={
                    "const": name,
                    "ui:hidden": True,
                    "x-category": op["category"],
                    "x-display-name": op["label"],
                    "x-is-trigger": False,
                },
            ),
        ),
    }
    for param in op["path_params"]:
        raw = param["name"]
        fields[_field_name("path", raw)] = (
            str,
            Field(
                ...,
                title=raw.replace("_", " ").title(),
                description=param["description"] or f"Paddle {raw} path parameter",
            ),
        )
    for param in op["query_params"]:
        raw = param["name"]
        required = param["required"]
        fields[_field_name("query", raw)] = (
            str if required else Optional[str],
            Field(
                ... if required else None,
                title=raw.replace("_", " ").replace(".", " ").title(),
                description=param["description"] or f"Paddle {raw} query parameter",
            ),
        )
    for param in op["header_params"]:
        raw = param["name"]
        fields[_field_name("header", raw)] = (
            str if param["required"] else Optional[str],
            Field(
                ... if param["required"] else None,
                title=raw.replace("-", " ").title(),
                description=param["description"] or f"Paddle {raw} header",
            ),
        )
    if op["body_supported"]:
        required = op["body_required_keys"]
        description = "JSON object sent as the request body."
        if required:
            description += " Required top-level keys: " + ", ".join(required) + "."
        description += " See " + op["docs_url"]
        fields["body_json"] = (
            str if op["body_required"] else Optional[str],
            Field(
                ... if op["body_required"] else None,
                title="Request Body (JSON)",
                description=description,
                json_schema_extra=_JSON_EDITOR,
            ),
        )
    return create_model(
        "Paddle" + "".join(word.title() for word in name.split("_")) + "Config",
        __module__=__name__,
        **fields,
    )


CONFIG_MODELS = {name: _make_config(op) for name, op in OPERATIONS.items()}
globals().update({model.__name__: model for model in CONFIG_MODELS.values()})
PaddleConfig = Annotated[
    Union[tuple(CONFIG_MODELS.values())], Discriminator("operation")
]


class PaddleNodeConfig(NodeConfig[PaddleConfig, PaddleApiKeyCredential]):
    model_config = ConfigDict(json_schema_extra={"x-agent-tool-provider": True})


def _parse_body(raw: Optional[str], op: dict[str, Any]) -> Optional[dict[str, Any]]:
    if raw is None or raw == "":
        if op["body_required"]:
            raise ValueError("Request Body is required")
        return None
    try:
        body = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("Request Body must contain valid JSON") from exc
    if not isinstance(body, dict):
        raise ValueError("Request Body must be a JSON object")
    missing = [key for key in op["body_required_keys"] if key not in body]
    if missing:
        raise ValueError("Request Body is missing required keys: " + ", ".join(missing))
    return body


class PaddleNode(WorkflowNode):
    """Run 99 documented Paddle Billing actions with a sandbox or live key."""

    integration_type = "automation-paddle"

    connection_evidence = ConnectionEvidence(
        operation="list_event_types", noun="event types", label_keys=("name", "description")
    )
    edit_examples = [
        "List my Paddle products and prices",
        "Find recent Paddle transactions",
        "Create a sandbox customer",
        "Get a subscription and its billing history",
    ]

    @classmethod
    def get_config_model(cls):
        return PaddleNodeConfig

    @staticmethod
    async def _request(
        credentials: PaddleApiKeyCredential, name: str, values: dict[str, Any]
    ) -> dict[str, Any]:
        op = OPERATIONS[name]
        key = credentials.api_key.strip()
        if not key:
            raise ValueError("Paddle API key is required")
        if key.startswith("pdl_live_") and credentials.environment != "live":
            raise ValueError("Live Paddle API keys require the live environment")
        if key.startswith("pdl_sdbx_") and credentials.environment != "sandbox":
            raise ValueError("Sandbox Paddle API keys require the sandbox environment")
        path = op["path"]
        for param in op["path_params"]:
            raw = param["name"]
            value = values.pop(_field_name("path", raw), None)
            if value is None or str(value).strip() in {"", ".", ".."}:
                raise ValueError(f"{raw} is required")
            path = path.replace("{" + raw + "}", quote(str(value), safe=""))
        query = {}
        for param in op["query_params"]:
            raw = param["name"]
            value = values.pop(_field_name("query", raw), None)
            if value is not None and value != "":
                query[raw] = value
            elif param["required"]:
                raise ValueError(f"{raw} is required")
        headers = {
            "Authorization": f"Bearer {key}",
            "Accept": "application/json",
            "Paddle-Version": "1",
        }
        for param in op["header_params"]:
            raw = param["name"]
            value = values.pop(_field_name("header", raw), None)
            if value is not None and value != "":
                headers[raw] = value
        body = _parse_body(values.pop("body_json", None), op) if op["body_supported"] else None
        started = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=60, follow_redirects=False) as client:
                response = await client.request(
                    op["method"],
                    API_HOSTS[credentials.environment] + path,
                    headers=headers,
                    params=query or None,
                    json=body,
                )
        except httpx.RequestError as exc:
            raise ValueError("Paddle API request failed") from exc
        try:
            payload: Any = response.json() if response.content else {}
        except ValueError:
            payload = {}
        if response.is_error or response.is_redirect:
            error = payload.get("error", {}) if isinstance(payload, dict) else {}
            if not isinstance(error, dict):
                error = {}
            code = error.get("code", "request_failed")
            detail = str(error.get("detail", "Paddle rejected the request"))
            detail = detail.replace(key, "[redacted]")[:500]
            raise ValueError(f"Paddle API error {response.status_code} ({code}): {detail}")
        result = {
            "status": "success",
            "operation": name,
            "status_code": response.status_code,
            "data": payload.get("data", payload) if isinstance(payload, dict) else payload,
            "timing_ms": {"api_request": round((time.monotonic() - started) * 1000, 2)},
        }
        if isinstance(payload, dict) and "meta" in payload:
            result["meta"] = payload["meta"]
        return result

    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(self.config, PaddleNodeConfig) or not self.config.credentials:
            raise ValueError("Add a Paddle server-side API key before running this action")
        config = self.config.config
        return await self._request(
            self.config.credentials,
            config.operation,
            config.model_dump(exclude={"operation"}, exclude_none=True),
        )
