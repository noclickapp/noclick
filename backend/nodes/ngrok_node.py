"""ngrok REST API v2 and AI Gateway workflow node.

The checked-in catalog defines 251 typed operations. Requests always target the
fixed provider API hosts and use bearer API-key authentication. Core requests
pin ngrok-version 2; AI Gateway requests use its separate control-plane API.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Annotated, Any, Dict, List, Literal, Optional, Union
from urllib.parse import parse_qs, quote, urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Discriminator, Field, create_model

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin


logger = logging.getLogger(__name__)
API_BASE = "https://api.ngrok.com"
API_VERSION = "2"
AI_GATEWAY_API_BASE = "https://api.ngrok.ai"
# Core catalog: ngrok/ngrok-openapi commit 2e400ad9c7043a93ef3fc8f9eeabe8b8047456b4.
# AI Gateway entries follow the current provider documentation linked per operation.
# Keep this catalog in the integration module so discovery requires no shared lists.
OPERATIONS: Dict[str, Dict[str, Any]] = json.loads(r'''
{
  "create_abuse_reports": {
    "operation_id": "AbuseReportsCreate",
    "display_name": "Create Abuse Reports",
    "category": "Abuse Reports",
    "description": "Creates a new abuse report which will be reviewed by our system and abuse response team. This API is only available to authorized accounts. Contact abuse@ngrok.com to request access",
    "method": "POST",
    "path": "/abuse_reports",
    "params": [],
    "body_fields": [
      {
        "name": "metadata",
        "type": "string",
        "required": false,
        "description": "arbitrary user-defined data about this abuse report. Optional, max 4096 bytes."
      },
      {
        "name": "urls",
        "type": "array",
        "required": true,
        "description": "a list of URLs containing suspected abusive content"
      }
    ]
  },
  "get_abuse_reports": {
    "operation_id": "AbuseReportsGet",
    "display_name": "Get Abuse Reports",
    "category": "Abuse Reports",
    "description": "Get the detailed status of abuse report by ID.",
    "method": "GET",
    "path": "/abuse_reports/{id}",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "a resource identifier"
      }
    ],
    "body_fields": []
  },
  "list_agent_ingresses": {
    "operation_id": "AgentIngressesList",
    "display_name": "List Agent Ingresses",
    "category": "Agent Ingresses",
    "description": "List all Agent Ingresses owned by this account",
    "method": "GET",
    "path": "/agent_ingresses",
    "params": [
      {
        "name": "before_id",
        "in": "query",
        "type": "string",
        "required": false,
        "description": "Expects a resource ID as its input. Returns earlier entries in the result set, sorted by ID."
      },
      {
        "name": "limit",
        "in": "query",
        "type": "string",
        "required": false,
        "description": "Constrains the number of results in the dataset. See the [API Overview](https://ngrok.com/docs/api/index#pagination) for details."
      },
      {
        "name": "filter",
        "in": "query",
        "type": "string",
        "required": false,
        "description": "A CEL expression to filter the list results. Supports logical and comparison operators to match on fields such as `id`, `metadata`, `created_at`, and more. See ngrok API Filtering for syntax and field details: https://ngrok.com/docs/api/api-filtering.\nFilterable fields: id, created_at, description, metadata, domain"
      }
    ],
    "body_fields": []
  },
  "create_agent_ingresses": {
    "operation_id": "AgentIngressesCreate",
    "display_name": "Create Agent Ingresses",
    "category": "Agent Ingresses",
    "description": "Create a new Agent Ingress. The ngrok agent can be configured to connect to ngrok via the new set of addresses on the returned Agent Ingress.",
    "method": "POST",
    "path": "/agent_ingresses",
    "params": [],
    "body_fields": [
      {
        "name": "certificate_management_policy",
        "type": "object",
        "required": false,
        "description": "configuration for automatic management of TLS certificates for this domain, or null if automatic management is disabled. Optional."
      },
      {
        "name": "description",
        "type": "string",
        "required": false,
        "description": "human-readable description of the use of this Agent Ingress. optional, max 255 bytes."
      },
      {
        "name": "domain",
        "type": "string",
        "required": true,
        "description": "the domain that you own to be used as the base domain name to generate regional agent ingress domains."
      },
      {
        "name": "metadata",
        "type": "string",
        "required": false,
        "description": "arbitrary user-defined machine-readable data of this Agent Ingress. optional, max 4096 bytes"
      }
    ]
  },
  "delete_agent_ingresses": {
    "operation_id": "AgentIngressesDelete",
    "display_name": "Delete Agent Ingresses",
    "category": "Agent Ingresses",
    "description": "Delete an Agent Ingress by ID",
    "method": "DELETE",
    "path": "/agent_ingresses/{id}",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "a resource identifier"
      }
    ],
    "body_fields": []
  },
  "get_agent_ingresses": {
    "operation_id": "AgentIngressesGet",
    "display_name": "Get Agent Ingresses",
    "category": "Agent Ingresses",
    "description": "Get the details of an Agent Ingress by ID.",
    "method": "GET",
    "path": "/agent_ingresses/{id}",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "a resource identifier"
      }
    ],
    "body_fields": []
  },
  "update_agent_ingresses": {
    "operation_id": "AgentIngressesUpdate",
    "display_name": "Update Agent Ingresses",
    "category": "Agent Ingresses",
    "description": "Update attributes of an Agent Ingress by ID.",
    "method": "PATCH",
    "path": "/agent_ingresses/{id}",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": ""
      }
    ],
    "body_fields": [
      {
        "name": "certificate_management_policy",
        "type": "object",
        "required": false,
        "description": "configuration for automatic management of TLS certificates for this domain, or null if automatic management is disabled. Optional."
      },
      {
        "name": "description",
        "type": "string",
        "required": false,
        "description": "human-readable description of the use of this Agent Ingress. optional, max 255 bytes."
      },
      {
        "name": "id",
        "type": "string",
        "required": false,
        "description": "n/a"
      },
      {
        "name": "metadata",
        "type": "string",
        "required": false,
        "description": "arbitrary user-defined machine-readable data of this Agent Ingress. optional, max 4096 bytes"
      }
    ]
  },
  "list_ai_gateway_api_keys": {
    "operation_id": "AiGatewayApiKeysList",
    "display_name": "List AI Gateway API Keys",
    "category": "AI Gateway API Keys",
    "description": "List all AI Gateway API Keys owned by account",
    "method": "GET",
    "path": "/api-keys",
    "params": [
      {
        "name": "beforeId",
        "in": "query",
        "type": "string",
        "required": false,
        "description": "Returns items before this resource identifier in descending ID order."
      },
      {
        "name": "limit",
        "in": "query",
        "type": "integer",
        "required": false,
        "description": "Maximum number of items to return. Defaults to 100 and may not exceed 100.",
        "minimum": 1,
        "maximum": 100
      }
    ],
    "body_fields": [],
    "ai_gateway": true,
    "source": "https://ngrok.com/docs/ai-gateway/api-reference/api-keys/list.md",
    "additional_properties": false
  },
  "create_ai_gateway_api_keys": {
    "operation_id": "AiGatewayApiKeysCreate",
    "display_name": "Create AI Gateway API Keys",
    "category": "AI Gateway API Keys",
    "description": "Create a new AI Gateway API Key",
    "method": "POST",
    "path": "/api-keys",
    "params": [],
    "body_fields": [
      {
        "name": "name",
        "type": "string",
        "required": false,
        "description": "User-friendly label for this API key.",
        "maxLength": 255
      },
      {
        "name": "description",
        "type": "string",
        "required": false,
        "description": "Human-readable description of this API key.",
        "maxLength": 255
      },
      {
        "name": "metadata",
        "type": "string",
        "required": false,
        "description": "Arbitrary user-defined metadata for this API key.",
        "maxLength": 4096
      }
    ],
    "ai_gateway": true,
    "source": "https://ngrok.com/docs/ai-gateway/api-reference/api-keys/create.md",
    "additional_properties": false
  },
  "delete_ai_gateway_api_keys": {
    "operation_id": "AiGatewayApiKeysDelete",
    "display_name": "Delete AI Gateway API Keys",
    "category": "AI Gateway API Keys",
    "description": "Delete an AI Gateway API Key",
    "method": "DELETE",
    "path": "/api-keys/{id}",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "Unique identifier for an AI Gateway API key."
      }
    ],
    "body_fields": [],
    "ai_gateway": true,
    "source": "https://ngrok.com/docs/ai-gateway/api-reference/api-keys/delete.md",
    "additional_properties": false
  },
  "get_ai_gateway_api_keys": {
    "operation_id": "AiGatewayApiKeysGet",
    "display_name": "Get AI Gateway API Keys",
    "category": "AI Gateway API Keys",
    "description": "Get an AI Gateway API Key by ID",
    "method": "GET",
    "path": "/api-keys/{id}",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "Unique identifier for an AI Gateway API key."
      }
    ],
    "body_fields": [],
    "ai_gateway": true,
    "source": "https://ngrok.com/docs/ai-gateway/api-reference/api-keys/get.md",
    "additional_properties": false
  },
  "update_ai_gateway_api_keys": {
    "operation_id": "AiGatewayApiKeysUpdate",
    "display_name": "Update AI Gateway API Keys",
    "category": "AI Gateway API Keys",
    "description": "Update an existing AI Gateway API Key by ID",
    "method": "PATCH",
    "path": "/api-keys/{id}",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "Unique identifier for an AI Gateway API key."
      }
    ],
    "body_fields": [
      {
        "name": "name",
        "type": "string",
        "required": false,
        "description": "User-friendly label for this API key.",
        "maxLength": 255,
        "nullable": true
      },
      {
        "name": "description",
        "type": "string",
        "required": false,
        "description": "Human-readable description of this API key.",
        "maxLength": 255,
        "nullable": true
      },
      {
        "name": "metadata",
        "type": "string",
        "required": false,
        "description": "Arbitrary user-defined metadata for this API key.",
        "maxLength": 4096,
        "nullable": true
      }
    ],
    "ai_gateway": true,
    "source": "https://ngrok.com/docs/ai-gateway/api-reference/api-keys/update.md",
    "additional_properties": false
  },
  "list_ai_gateway_provider_keys": {
    "operation_id": "AiGatewayProviderKeysList",
    "display_name": "List AI Gateway Provider Keys",
    "category": "AI Gateway Provider Keys",
    "description": "List AI Gateway Provider Keys",
    "method": "GET",
    "path": "/provider-keys",
    "params": [
      {
        "name": "beforeId",
        "in": "query",
        "type": "string",
        "required": false,
        "description": "Returns items before this resource identifier in descending ID order."
      },
      {
        "name": "limit",
        "in": "query",
        "type": "integer",
        "required": false,
        "description": "Maximum number of items to return. Defaults to 100 and may not exceed 100.",
        "minimum": 1,
        "maximum": 100
      },
      {
        "name": "provider",
        "in": "query",
        "type": "string",
        "required": false,
        "description": "Only returns keys matching the provider."
      }
    ],
    "body_fields": [],
    "ai_gateway": true,
    "source": "https://ngrok.com/docs/ai-gateway/api-reference/provider-keys/list.md",
    "additional_properties": false
  },
  "create_ai_gateway_provider_keys": {
    "operation_id": "AiGatewayProviderKeysCreate",
    "display_name": "Create AI Gateway Provider Keys",
    "category": "AI Gateway Provider Keys",
    "description": "Create a new AI Gateway Provider Key",
    "method": "POST",
    "path": "/provider-keys",
    "params": [],
    "body_fields": [
      {
        "name": "providerId",
        "type": "string",
        "required": true,
        "description": "Which AI provider this key is for, for example `openai` or `anthropic`."
      },
      {
        "name": "value",
        "type": "string",
        "required": true,
        "description": "Plaintext provider key value. Write-only; never returned in responses."
      },
      {
        "name": "name",
        "type": "string",
        "required": true,
        "description": "User-defined label for this provider key.",
        "maxLength": 255
      },
      {
        "name": "description",
        "type": "string",
        "required": false,
        "description": "Human-readable description of this provider key.",
        "maxLength": 255
      },
      {
        "name": "metadata",
        "type": "string",
        "required": false,
        "description": "Arbitrary user-defined metadata for this provider key.",
        "maxLength": 4096
      }
    ],
    "ai_gateway": true,
    "source": "https://ngrok.com/docs/ai-gateway/api-reference/provider-keys/create.md",
    "additional_properties": false
  },
  "delete_ai_gateway_provider_keys": {
    "operation_id": "AiGatewayProviderKeysDelete",
    "display_name": "Delete AI Gateway Provider Keys",
    "category": "AI Gateway Provider Keys",
    "description": "Delete an AI Gateway Provider Key",
    "method": "DELETE",
    "path": "/provider-keys/{id}",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "Unique identifier for an AI Gateway provider key."
      }
    ],
    "body_fields": [],
    "ai_gateway": true,
    "source": "https://ngrok.com/docs/ai-gateway/api-reference/provider-keys/delete.md",
    "additional_properties": false
  },
  "get_ai_gateway_provider_keys": {
    "operation_id": "AiGatewayProviderKeysGet",
    "display_name": "Get AI Gateway Provider Keys",
    "category": "AI Gateway Provider Keys",
    "description": "Get an AI Gateway Provider Key by ID",
    "method": "GET",
    "path": "/provider-keys/{id}",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "Unique identifier for an AI Gateway provider key."
      }
    ],
    "body_fields": [],
    "ai_gateway": true,
    "source": "https://ngrok.com/docs/ai-gateway/api-reference/provider-keys/get.md",
    "additional_properties": false
  },
  "update_ai_gateway_provider_keys": {
    "operation_id": "AiGatewayProviderKeysUpdate",
    "display_name": "Update AI Gateway Provider Keys",
    "category": "AI Gateway Provider Keys",
    "description": "Update an existing AI Gateway Provider Key by ID",
    "method": "PATCH",
    "path": "/provider-keys/{id}",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "Unique identifier for an AI Gateway provider key."
      }
    ],
    "body_fields": [
      {
        "name": "name",
        "type": "string",
        "required": false,
        "description": "User-defined label for this provider key.",
        "maxLength": 255,
        "nullable": true
      },
      {
        "name": "description",
        "type": "string",
        "required": false,
        "description": "Human-readable description of this provider key.",
        "maxLength": 255,
        "nullable": true
      },
      {
        "name": "metadata",
        "type": "string",
        "required": false,
        "description": "Arbitrary user-defined metadata for this provider key.",
        "maxLength": 4096,
        "nullable": true
      }
    ],
    "ai_gateway": true,
    "source": "https://ngrok.com/docs/ai-gateway/api-reference/provider-keys/update.md",
    "additional_properties": false
  },
  "list_api_keys": {
    "operation_id": "ApiKeysList",
    "display_name": "List API Keys",
    "category": "API Keys",
    "description": "List all API keys owned by this account",
    "method": "GET",
    "path": "/api_keys",
    "params": [
      {
        "name": "before_id",
        "in": "query",
        "type": "string",
        "required": false,
        "description": "Expects a resource ID as its input. Returns earlier entries in the result set, sorted by ID."
      },
      {
        "name": "limit",
        "in": "query",
        "type": "string",
        "required": false,
        "description": "Constrains the number of results in the dataset. See the [API Overview](https://ngrok.com/docs/api/index#pagination) for details."
      },
      {
        "name": "filter",
        "in": "query",
        "type": "string",
        "required": false,
        "description": "A CEL expression to filter the list results. Supports logical and comparison operators to match on fields such as `id`, `metadata`, `created_at`, and more. See ngrok API Filtering for syntax and field details: https://ngrok.com/docs/api/api-filtering.\nFilterable fields: id, description, metadata, owner_id, created_at"
      }
    ],
    "body_fields": []
  },
  "create_api_keys": {
    "operation_id": "ApiKeysCreate",
    "display_name": "Create API Keys",
    "category": "API Keys",
    "description": "Create a new API key. The generated API key can be used to authenticate to the ngrok API.",
    "method": "POST",
    "path": "/api_keys",
    "params": [],
    "body_fields": [
      {
        "name": "description",
        "type": "string",
        "required": false,
        "description": "human-readable description of what uses the API key to authenticate. optional, max 255 bytes."
      },
      {
        "name": "metadata",
        "type": "string",
        "required": false,
        "description": "arbitrary user-defined data of this API key. optional, max 4096 bytes"
      },
      {
        "name": "owner_id",
        "type": "string",
        "required": false,
        "description": "If supplied at credential creation, ownership will be assigned to the specified User or Bot. Only admins may specify an owner other than themselves. Defaults to the authenticated User or Bot."
      }
    ]
  },
  "delete_api_keys": {
    "operation_id": "ApiKeysDelete",
    "display_name": "Delete API Keys",
    "category": "API Keys",
    "description": "Delete an API key by ID",
    "method": "DELETE",
    "path": "/api_keys/{id}",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "a resource identifier"
      }
    ],
    "body_fields": []
  },
  "get_api_keys": {
    "operation_id": "ApiKeysGet",
    "display_name": "Get API Keys",
    "category": "API Keys",
    "description": "Get the details of an API key by ID.",
    "method": "GET",
    "path": "/api_keys/{id}",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "a resource identifier"
      }
    ],
    "body_fields": []
  },
  "update_api_keys": {
    "operation_id": "ApiKeysUpdate",
    "display_name": "Update API Keys",
    "category": "API Keys",
    "description": "Update attributes of an API key by ID.",
    "method": "PATCH",
    "path": "/api_keys/{id}",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": ""
      }
    ],
    "body_fields": [
      {
        "name": "description",
        "type": "string",
        "required": false,
        "description": "human-readable description of what uses the API key to authenticate. optional, max 255 bytes."
      },
      {
        "name": "id",
        "type": "string",
        "required": false,
        "description": "n/a"
      },
      {
        "name": "metadata",
        "type": "string",
        "required": false,
        "description": "arbitrary user-defined data of this API key. optional, max 4096 bytes"
      }
    ]
  },
  "list_application_sessions": {
    "operation_id": "ApplicationSessionsList",
    "display_name": "List Application Sessions",
    "category": "Application Sessions",
    "description": "List all application sessions for this account.",
    "method": "GET",
    "path": "/app/sessions",
    "params": [
      {
        "name": "before_id",
        "in": "query",
        "type": "string",
        "required": false,
        "description": ""
      },
      {
        "name": "limit",
        "in": "query",
        "type": "string",
        "required": false,
        "description": ""
      }
    ],
    "body_fields": []
  },
  "delete_application_sessions": {
    "operation_id": "ApplicationSessionsDelete",
    "display_name": "Delete Application Sessions",
    "category": "Application Sessions",
    "description": "Delete an application session by ID.",
    "method": "DELETE",
    "path": "/app/sessions/{id}",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "a resource identifier"
      }
    ],
    "body_fields": []
  },
  "get_application_sessions": {
    "operation_id": "ApplicationSessionsGet",
    "display_name": "Get Application Sessions",
    "category": "Application Sessions",
    "description": "Get an application session by ID.",
    "method": "GET",
    "path": "/app/sessions/{id}",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "a resource identifier"
      }
    ],
    "body_fields": []
  },
  "list_application_users": {
    "operation_id": "ApplicationUsersList",
    "display_name": "List Application Users",
    "category": "Application Users",
    "description": "List all application users for this account.",
    "method": "GET",
    "path": "/app/users",
    "params": [
      {
        "name": "before_id",
        "in": "query",
        "type": "string",
        "required": false,
        "description": ""
      },
      {
        "name": "limit",
        "in": "query",
        "type": "string",
        "required": false,
        "description": ""
      }
    ],
    "body_fields": []
  },
  "delete_application_users": {
    "operation_id": "ApplicationUsersDelete",
    "display_name": "Delete Application Users",
    "category": "Application Users",
    "description": "Delete an application user by ID.",
    "method": "DELETE",
    "path": "/app/users/{id}",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "a resource identifier"
      }
    ],
    "body_fields": []
  },
  "get_application_users": {
    "operation_id": "ApplicationUsersGet",
    "display_name": "Get Application Users",
    "category": "Application Users",
    "description": "Get an application user by ID.",
    "method": "GET",
    "path": "/app/users/{id}",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "a resource identifier"
      }
    ],
    "body_fields": []
  },
  "list_failover_backends": {
    "operation_id": "FailoverBackendsList",
    "display_name": "List Failover Backends",
    "category": "Failover Backends",
    "description": "List all Failover backends on this account",
    "method": "GET",
    "path": "/backends/failover",
    "params": [
      {
        "name": "before_id",
        "in": "query",
        "type": "string",
        "required": false,
        "description": ""
      },
      {
        "name": "limit",
        "in": "query",
        "type": "string",
        "required": false,
        "description": ""
      }
    ],
    "body_fields": []
  },
  "create_failover_backends": {
    "operation_id": "FailoverBackendsCreate",
    "display_name": "Create Failover Backends",
    "category": "Failover Backends",
    "description": "Create a new Failover backend",
    "method": "POST",
    "path": "/backends/failover",
    "params": [],
    "body_fields": [
      {
        "name": "backends",
        "type": "array",
        "required": false,
        "description": "the ids of the child backends in order"
      },
      {
        "name": "description",
        "type": "string",
        "required": false,
        "description": "human-readable description of this backend. Optional"
      },
      {
        "name": "metadata",
        "type": "string",
        "required": false,
        "description": "arbitrary user-defined machine-readable data of this backend. Optional"
      }
    ]
  },
  "delete_failover_backends": {
    "operation_id": "FailoverBackendsDelete",
    "display_name": "Delete Failover Backends",
    "category": "Failover Backends",
    "description": "Delete a Failover backend by ID.",
    "method": "DELETE",
    "path": "/backends/failover/{id}",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "a resource identifier"
      }
    ],
    "body_fields": []
  },
  "get_failover_backends": {
    "operation_id": "FailoverBackendsGet",
    "display_name": "Get Failover Backends",
    "category": "Failover Backends",
    "description": "Get detailed information about a Failover backend by ID",
    "method": "GET",
    "path": "/backends/failover/{id}",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "a resource identifier"
      }
    ],
    "body_fields": []
  },
  "update_failover_backends": {
    "operation_id": "FailoverBackendsUpdate",
    "display_name": "Update Failover Backends",
    "category": "Failover Backends",
    "description": "Update Failover backend by ID",
    "method": "PATCH",
    "path": "/backends/failover/{id}",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": ""
      }
    ],
    "body_fields": [
      {
        "name": "backends",
        "type": "array",
        "required": false,
        "description": "the ids of the child backends in order"
      },
      {
        "name": "description",
        "type": "string",
        "required": false,
        "description": "human-readable description of this backend. Optional"
      },
      {
        "name": "id",
        "type": "string",
        "required": false,
        "description": "n/a"
      },
      {
        "name": "metadata",
        "type": "string",
        "required": false,
        "description": "arbitrary user-defined machine-readable data of this backend. Optional"
      }
    ]
  },
  "list_http_response_backends": {
    "operation_id": "HttpResponseBackendsList",
    "display_name": "List HTTP Response Backends",
    "category": "HTTP Response Backends",
    "description": "List",
    "method": "GET",
    "path": "/backends/http_response",
    "params": [
      {
        "name": "before_id",
        "in": "query",
        "type": "string",
        "required": false,
        "description": ""
      },
      {
        "name": "limit",
        "in": "query",
        "type": "string",
        "required": false,
        "description": ""
      }
    ],
    "body_fields": []
  },
  "create_http_response_backends": {
    "operation_id": "HttpResponseBackendsCreate",
    "display_name": "Create HTTP Response Backends",
    "category": "HTTP Response Backends",
    "description": "Create",
    "method": "POST",
    "path": "/backends/http_response",
    "params": [],
    "body_fields": [
      {
        "name": "body",
        "type": "string",
        "required": false,
        "description": "body to return as fixed content"
      },
      {
        "name": "description",
        "type": "string",
        "required": false,
        "description": "human-readable description of this backend. Optional"
      },
      {
        "name": "headers",
        "type": "object",
        "required": false,
        "description": "headers to return"
      },
      {
        "name": "metadata",
        "type": "string",
        "required": false,
        "description": "arbitrary user-defined machine-readable data of this backend. Optional"
      },
      {
        "name": "status_code",
        "type": "integer",
        "required": false,
        "description": "status code to return"
      }
    ]
  },
  "delete_http_response_backends": {
    "operation_id": "HttpResponseBackendsDelete",
    "display_name": "Delete HTTP Response Backends",
    "category": "HTTP Response Backends",
    "description": "Delete",
    "method": "DELETE",
    "path": "/backends/http_response/{id}",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "a resource identifier"
      }
    ],
    "body_fields": []
  },
  "get_http_response_backends": {
    "operation_id": "HttpResponseBackendsGet",
    "display_name": "Get HTTP Response Backends",
    "category": "HTTP Response Backends",
    "description": "Get",
    "method": "GET",
    "path": "/backends/http_response/{id}",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "a resource identifier"
      }
    ],
    "body_fields": []
  },
  "update_http_response_backends": {
    "operation_id": "HttpResponseBackendsUpdate",
    "display_name": "Update HTTP Response Backends",
    "category": "HTTP Response Backends",
    "description": "Update",
    "method": "PATCH",
    "path": "/backends/http_response/{id}",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": ""
      }
    ],
    "body_fields": [
      {
        "name": "body",
        "type": "string",
        "required": false,
        "description": "body to return as fixed content"
      },
      {
        "name": "description",
        "type": "string",
        "required": false,
        "description": "human-readable description of this backend. Optional"
      },
      {
        "name": "headers",
        "type": "object",
        "required": false,
        "description": "headers to return"
      },
      {
        "name": "id",
        "type": "string",
        "required": false,
        "description": "n/a"
      },
      {
        "name": "metadata",
        "type": "string",
        "required": false,
        "description": "arbitrary user-defined machine-readable data of this backend. Optional"
      },
      {
        "name": "status_code",
        "type": "integer",
        "required": false,
        "description": "status code to return"
      }
    ]
  },
  "list_static_backends": {
    "operation_id": "StaticBackendsList",
    "display_name": "List Static Backends",
    "category": "Static Backends",
    "description": "List all static backends on this account",
    "method": "GET",
    "path": "/backends/static",
    "params": [
      {
        "name": "before_id",
        "in": "query",
        "type": "string",
        "required": false,
        "description": ""
      },
      {
        "name": "limit",
        "in": "query",
        "type": "string",
        "required": false,
        "description": ""
      }
    ],
    "body_fields": []
  },
  "create_static_backends": {
    "operation_id": "StaticBackendsCreate",
    "display_name": "Create Static Backends",
    "category": "Static Backends",
    "description": "Create a new static backend",
    "method": "POST",
    "path": "/backends/static",
    "params": [],
    "body_fields": [
      {
        "name": "address",
        "type": "string",
        "required": false,
        "description": "the address to forward to"
      },
      {
        "name": "description",
        "type": "string",
        "required": false,
        "description": "human-readable description of this backend. Optional"
      },
      {
        "name": "metadata",
        "type": "string",
        "required": false,
        "description": "arbitrary user-defined machine-readable data of this backend. Optional"
      },
      {
        "name": "tls",
        "type": "object",
        "required": false,
        "description": "tls configuration to use"
      }
    ]
  },
  "delete_static_backends": {
    "operation_id": "StaticBackendsDelete",
    "display_name": "Delete Static Backends",
    "category": "Static Backends",
    "description": "Delete a static backend by ID.",
    "method": "DELETE",
    "path": "/backends/static/{id}",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "a resource identifier"
      }
    ],
    "body_fields": []
  },
  "get_static_backends": {
    "operation_id": "StaticBackendsGet",
    "display_name": "Get Static Backends",
    "category": "Static Backends",
    "description": "Get detailed information about a static backend by ID",
    "method": "GET",
    "path": "/backends/static/{id}",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "a resource identifier"
      }
    ],
    "body_fields": []
  },
  "update_static_backends": {
    "operation_id": "StaticBackendsUpdate",
    "display_name": "Update Static Backends",
    "category": "Static Backends",
    "description": "Update static backend by ID",
    "method": "PATCH",
    "path": "/backends/static/{id}",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": ""
      }
    ],
    "body_fields": [
      {
        "name": "address",
        "type": "string",
        "required": false,
        "description": "the address to forward to"
      },
      {
        "name": "description",
        "type": "string",
        "required": false,
        "description": "human-readable description of this backend. Optional"
      },
      {
        "name": "id",
        "type": "string",
        "required": false,
        "description": "n/a"
      },
      {
        "name": "metadata",
        "type": "string",
        "required": false,
        "description": "arbitrary user-defined machine-readable data of this backend. Optional"
      },
      {
        "name": "tls",
        "type": "object",
        "required": false,
        "description": "tls configuration to use"
      }
    ]
  },
  "list_tunnel_group_backends": {
    "operation_id": "TunnelGroupBackendsList",
    "display_name": "List Tunnel Group Backends",
    "category": "Tunnel Group Backends",
    "description": "List all TunnelGroup backends on this account",
    "method": "GET",
    "path": "/backends/tunnel_group",
    "params": [
      {
        "name": "before_id",
        "in": "query",
        "type": "string",
        "required": false,
        "description": ""
      },
      {
        "name": "limit",
        "in": "query",
        "type": "string",
        "required": false,
        "description": ""
      }
    ],
    "body_fields": []
  },
  "create_tunnel_group_backends": {
    "operation_id": "TunnelGroupBackendsCreate",
    "display_name": "Create Tunnel Group Backends",
    "category": "Tunnel Group Backends",
    "description": "Create a new TunnelGroup backend",
    "method": "POST",
    "path": "/backends/tunnel_group",
    "params": [],
    "body_fields": [
      {
        "name": "description",
        "type": "string",
        "required": false,
        "description": "human-readable description of this backend. Optional"
      },
      {
        "name": "labels",
        "type": "object",
        "required": false,
        "description": "labels to watch for tunnels on, e.g. app->foo, dc->bar"
      },
      {
        "name": "metadata",
        "type": "string",
        "required": false,
        "description": "arbitrary user-defined machine-readable data of this backend. Optional"
      }
    ]
  },
  "delete_tunnel_group_backends": {
    "operation_id": "TunnelGroupBackendsDelete",
    "display_name": "Delete Tunnel Group Backends",
    "category": "Tunnel Group Backends",
    "description": "Delete a TunnelGroup backend by ID.",
    "method": "DELETE",
    "path": "/backends/tunnel_group/{id}",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "a resource identifier"
      }
    ],
    "body_fields": []
  },
  "get_tunnel_group_backends": {
    "operation_id": "TunnelGroupBackendsGet",
    "display_name": "Get Tunnel Group Backends",
    "category": "Tunnel Group Backends",
    "description": "Get detailed information about a TunnelGroup backend by ID",
    "method": "GET",
    "path": "/backends/tunnel_group/{id}",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "a resource identifier"
      }
    ],
    "body_fields": []
  },
  "update_tunnel_group_backends": {
    "operation_id": "TunnelGroupBackendsUpdate",
    "display_name": "Update Tunnel Group Backends",
    "category": "Tunnel Group Backends",
    "description": "Update TunnelGroup backend by ID",
    "method": "PATCH",
    "path": "/backends/tunnel_group/{id}",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": ""
      }
    ],
    "body_fields": [
      {
        "name": "description",
        "type": "string",
        "required": false,
        "description": "human-readable description of this backend. Optional"
      },
      {
        "name": "id",
        "type": "string",
        "required": false,
        "description": "n/a"
      },
      {
        "name": "labels",
        "type": "object",
        "required": false,
        "description": "labels to watch for tunnels on, e.g. app->foo, dc->bar"
      },
      {
        "name": "metadata",
        "type": "string",
        "required": false,
        "description": "arbitrary user-defined machine-readable data of this backend. Optional"
      }
    ]
  },
  "list_weighted_backends": {
    "operation_id": "WeightedBackendsList",
    "display_name": "List Weighted Backends",
    "category": "Weighted Backends",
    "description": "List all Weighted backends on this account",
    "method": "GET",
    "path": "/backends/weighted",
    "params": [
      {
        "name": "before_id",
        "in": "query",
        "type": "string",
        "required": false,
        "description": ""
      },
      {
        "name": "limit",
        "in": "query",
        "type": "string",
        "required": false,
        "description": ""
      }
    ],
    "body_fields": []
  },
  "create_weighted_backends": {
    "operation_id": "WeightedBackendsCreate",
    "display_name": "Create Weighted Backends",
    "category": "Weighted Backends",
    "description": "Create a new Weighted backend",
    "method": "POST",
    "path": "/backends/weighted",
    "params": [],
    "body_fields": [
      {
        "name": "backends",
        "type": "object",
        "required": false,
        "description": "the ids of the child backends to their weights [0-10000]"
      },
      {
        "name": "description",
        "type": "string",
        "required": false,
        "description": "human-readable description of this backend. Optional"
      },
      {
        "name": "metadata",
        "type": "string",
        "required": false,
        "description": "arbitrary user-defined machine-readable data of this backend. Optional"
      }
    ]
  },
  "delete_weighted_backends": {
    "operation_id": "WeightedBackendsDelete",
    "display_name": "Delete Weighted Backends",
    "category": "Weighted Backends",
    "description": "Delete a Weighted backend by ID.",
    "method": "DELETE",
    "path": "/backends/weighted/{id}",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "a resource identifier"
      }
    ],
    "body_fields": []
  },
  "get_weighted_backends": {
    "operation_id": "WeightedBackendsGet",
    "display_name": "Get Weighted Backends",
    "category": "Weighted Backends",
    "description": "Get detailed information about a Weighted backend by ID",
    "method": "GET",
    "path": "/backends/weighted/{id}",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "a resource identifier"
      }
    ],
    "body_fields": []
  },
  "update_weighted_backends": {
    "operation_id": "WeightedBackendsUpdate",
    "display_name": "Update Weighted Backends",
    "category": "Weighted Backends",
    "description": "Update Weighted backend by ID",
    "method": "PATCH",
    "path": "/backends/weighted/{id}",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": ""
      }
    ],
    "body_fields": [
      {
        "name": "backends",
        "type": "object",
        "required": false,
        "description": "the ids of the child backends to their weights [0-10000]"
      },
      {
        "name": "description",
        "type": "string",
        "required": false,
        "description": "human-readable description of this backend. Optional"
      },
      {
        "name": "id",
        "type": "string",
        "required": false,
        "description": "n/a"
      },
      {
        "name": "metadata",
        "type": "string",
        "required": false,
        "description": "arbitrary user-defined machine-readable data of this backend. Optional"
      }
    ]
  },
  "list_bot_users": {
    "operation_id": "BotUsersList",
    "display_name": "List Bot Users",
    "category": "Bot Users",
    "description": "List all bot users in this account.",
    "method": "GET",
    "path": "/bot_users",
    "params": [
      {
        "name": "before_id",
        "in": "query",
        "type": "string",
        "required": false,
        "description": ""
      },
      {
        "name": "limit",
        "in": "query",
        "type": "string",
        "required": false,
        "description": ""
      }
    ],
    "body_fields": []
  },
  "create_bot_users": {
    "operation_id": "BotUsersCreate",
    "display_name": "Create Bot Users",
    "category": "Bot Users",
    "description": "Create a new bot user",
    "method": "POST",
    "path": "/bot_users",
    "params": [],
    "body_fields": [
      {
        "name": "active",
        "type": "boolean",
        "required": false,
        "description": "whether or not the service user is active"
      },
      {
        "name": "name",
        "type": "string",
        "required": false,
        "description": "human-readable name used to identify the service user"
      }
    ]
  },
  "delete_bot_users": {
    "operation_id": "BotUsersDelete",
    "display_name": "Delete Bot Users",
    "category": "Bot Users",
    "description": "Delete a bot user by ID",
    "method": "DELETE",
    "path": "/bot_users/{id}",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "a resource identifier"
      }
    ],
    "body_fields": []
  },
  "get_bot_users": {
    "operation_id": "BotUsersGet",
    "display_name": "Get Bot Users",
    "category": "Bot Users",
    "description": "Get the details of a Bot User by ID.",
    "method": "GET",
    "path": "/bot_users/{id}",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "a resource identifier"
      }
    ],
    "body_fields": []
  },
  "update_bot_users": {
    "operation_id": "BotUsersUpdate",
    "display_name": "Update Bot Users",
    "category": "Bot Users",
    "description": "Update attributes of a bot user by ID.",
    "method": "PATCH",
    "path": "/bot_users/{id}",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": ""
      }
    ],
    "body_fields": [
      {
        "name": "active",
        "type": "boolean",
        "required": false,
        "description": "whether or not the service user is active"
      },
      {
        "name": "id",
        "type": "string",
        "required": false,
        "description": "n/a"
      },
      {
        "name": "name",
        "type": "string",
        "required": false,
        "description": "human-readable name used to identify the service user"
      }
    ]
  },
  "list_certificate_authorities": {
    "operation_id": "CertificateAuthoritiesList",
    "display_name": "List Certificate Authorities",
    "category": "Certificate Authorities",
    "description": "List all Certificate Authority on this account",
    "method": "GET",
    "path": "/certificate_authorities",
    "params": [
      {
        "name": "before_id",
        "in": "query",
        "type": "string",
        "required": false,
        "description": "Expects a resource ID as its input. Returns earlier entries in the result set, sorted by ID."
      },
      {
        "name": "limit",
        "in": "query",
        "type": "string",
        "required": false,
        "description": "Constrains the number of results in the dataset. See the [API Overview](https://ngrok.com/docs/api/index#pagination) for details."
      },
      {
        "name": "filter",
        "in": "query",
        "type": "string",
        "required": false,
        "description": "A CEL expression to filter the list results. Supports logical and comparison operators to match on fields such as `id`, `metadata`, `created_at`, and more. See ngrok API Filtering for syntax and field details: https://ngrok.com/docs/api/api-filtering.\nFilterable fields: id, created_at, description, metadata, subject_common_name, not_before, not_after"
      }
    ],
    "body_fields": []
  },
  "create_certificate_authorities": {
    "operation_id": "CertificateAuthoritiesCreate",
    "display_name": "Create Certificate Authorities",
    "category": "Certificate Authorities",
    "description": "Upload a new Certificate Authority",
    "method": "POST",
    "path": "/certificate_authorities",
    "params": [],
    "body_fields": [
      {
        "name": "ca_pem",
        "type": "string",
        "required": true,
        "description": "raw PEM of the Certificate Authority"
      },
      {
        "name": "description",
        "type": "string",
        "required": false,
        "description": "human-readable description of this Certificate Authority. optional, max 255 bytes."
      },
      {
        "name": "metadata",
        "type": "string",
        "required": false,
        "description": "arbitrary user-defined machine-readable data of this Certificate Authority. optional, max 4096 bytes."
      }
    ]
  },
  "delete_certificate_authorities": {
    "operation_id": "CertificateAuthoritiesDelete",
    "display_name": "Delete Certificate Authorities",
    "category": "Certificate Authorities",
    "description": "Delete a Certificate Authority",
    "method": "DELETE",
    "path": "/certificate_authorities/{id}",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "a resource identifier"
      }
    ],
    "body_fields": []
  },
  "get_certificate_authorities": {
    "operation_id": "CertificateAuthoritiesGet",
    "display_name": "Get Certificate Authorities",
    "category": "Certificate Authorities",
    "description": "Get detailed information about a certificate authority",
    "method": "GET",
    "path": "/certificate_authorities/{id}",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "a resource identifier"
      }
    ],
    "body_fields": []
  },
  "update_certificate_authorities": {
    "operation_id": "CertificateAuthoritiesUpdate",
    "display_name": "Update Certificate Authorities",
    "category": "Certificate Authorities",
    "description": "Update attributes of a Certificate Authority by ID",
    "method": "PATCH",
    "path": "/certificate_authorities/{id}",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": ""
      }
    ],
    "body_fields": [
      {
        "name": "description",
        "type": "string",
        "required": false,
        "description": "human-readable description of this Certificate Authority. optional, max 255 bytes."
      },
      {
        "name": "id",
        "type": "string",
        "required": false,
        "description": "n/a"
      },
      {
        "name": "metadata",
        "type": "string",
        "required": false,
        "description": "arbitrary user-defined machine-readable data of this Certificate Authority. optional, max 4096 bytes."
      }
    ]
  },
  "list_credentials": {
    "operation_id": "CredentialsList",
    "display_name": "List Credentials",
    "category": "Credentials",
    "description": "List all tunnel authtoken credentials on this account",
    "method": "GET",
    "path": "/credentials",
    "params": [
      {
        "name": "before_id",
        "in": "query",
        "type": "string",
        "required": false,
        "description": "Expects a resource ID as its input. Returns earlier entries in the result set, sorted by ID."
      },
      {
        "name": "limit",
        "in": "query",
        "type": "string",
        "required": false,
        "description": "Constrains the number of results in the dataset. See the [API Overview](https://ngrok.com/docs/api/index#pagination) for details."
      },
      {
        "name": "filter",
        "in": "query",
        "type": "string",
        "required": false,
        "description": "A CEL expression to filter the list results. Supports logical and comparison operators to match on fields such as `id`, `metadata`, `created_at`, and more. See ngrok API Filtering for syntax and field details: https://ngrok.com/docs/api/api-filtering.\nFilterable fields: id, description, metadata, owner_id, acl, created_at"
      }
    ],
    "body_fields": []
  },
  "create_credentials": {
    "operation_id": "CredentialsCreate",
    "display_name": "Create Credentials",
    "category": "Credentials",
    "description": "Create a new tunnel authtoken credential. This authtoken credential can be used to start a new tunnel session. The response to this API call is the only time the generated token is available. If you need it for future use, you must save it securely yourself.",
    "method": "POST",
    "path": "/credentials",
    "params": [],
    "body_fields": [
      {
        "name": "acl",
        "type": "array",
        "required": false,
        "description": "optional list of ACL rules. If unspecified, the credential will have no restrictions. The only allowed ACL rule at this time is the `bind` rule. The `bind` rule allows the caller to restrict what domains, addresses, and labels the token is allowed to bind. For example, to allow the token to open a tunnel on example.ngrok.io your ACL would include the rule `bind:example.ngrok.io`. Bind rules for domains may specify a leading wildcard to match multiple domains with a common suffix. For example, you may specify a rule of `bind:*.example.com` which will allow `x.example.com`, `y.example.com`, `*.example.com`, etc. Bind rules for labels may specify a wildcard key and/or value to match multiple labels. For example, you may specify a rule of `bind:*=example` which will allow `x=example`, `y=example`, etc. A rule of `'*'` is equivalent to no acl at all and will explicitly permit all actions."
      },
      {
        "name": "description",
        "type": "string",
        "required": false,
        "description": "human-readable description of who or what will use the credential to authenticate. Optional, max 255 bytes."
      },
      {
        "name": "metadata",
        "type": "string",
        "required": false,
        "description": "arbitrary user-defined machine-readable data of this credential. Optional, max 4096 bytes."
      },
      {
        "name": "owner_id",
        "type": "string",
        "required": false,
        "description": "If supplied at credential creation, ownership will be assigned to the specified User or Service User. Only admins may specify an owner other than themselves. Defaults to the authenticated User or Service User. Accepts one of: User ID, User email, or SCIM User ID."
      }
    ]
  },
  "delete_credentials": {
    "operation_id": "CredentialsDelete",
    "display_name": "Delete Credentials",
    "category": "Credentials",
    "description": "Delete a tunnel authtoken credential by ID",
    "method": "DELETE",
    "path": "/credentials/{id}",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "a resource identifier"
      }
    ],
    "body_fields": []
  },
  "get_credentials": {
    "operation_id": "CredentialsGet",
    "display_name": "Get Credentials",
    "category": "Credentials",
    "description": "Get detailed information about a tunnel authtoken credential",
    "method": "GET",
    "path": "/credentials/{id}",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "a resource identifier"
      }
    ],
    "body_fields": []
  },
  "update_credentials": {
    "operation_id": "CredentialsUpdate",
    "display_name": "Update Credentials",
    "category": "Credentials",
    "description": "Update attributes of an tunnel authtoken credential by ID",
    "method": "PATCH",
    "path": "/credentials/{id}",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": ""
      }
    ],
    "body_fields": [
      {
        "name": "acl",
        "type": "array",
        "required": false,
        "description": "optional list of ACL rules. If unspecified, the credential will have no restrictions. The only allowed ACL rule at this time is the `bind` rule. The `bind` rule allows the caller to restrict what domains, addresses, and labels the token is allowed to bind. For example, to allow the token to open a tunnel on example.ngrok.io your ACL would include the rule `bind:example.ngrok.io`. Bind rules for domains may specify a leading wildcard to match multiple domains with a common suffix. For example, you may specify a rule of `bind:*.example.com` which will allow `x.example.com`, `y.example.com`, `*.example.com`, etc. Bind rules for labels may specify a wildcard key and/or value to match multiple labels. For example, you may specify a rule of `bind:*=example` which will allow `x=example`, `y=example`, etc. A rule of `'*'` is equivalent to no acl at all and will explicitly permit all actions."
      },
      {
        "name": "description",
        "type": "string",
        "required": false,
        "description": "human-readable description of who or what will use the credential to authenticate. Optional, max 255 bytes."
      },
      {
        "name": "id",
        "type": "string",
        "required": false,
        "description": "n/a"
      },
      {
        "name": "metadata",
        "type": "string",
        "required": false,
        "description": "arbitrary user-defined machine-readable data of this credential. Optional, max 4096 bytes."
      }
    ]
  },
  "list_edges_https": {
    "operation_id": "EdgesHttpsList",
    "display_name": "List Edges HTTPS",
    "category": "Edges HTTPS",
    "description": "Returns a list of all HTTPS Edges on this account",
    "method": "GET",
    "path": "/edges/https",
    "params": [
      {
        "name": "before_id",
        "in": "query",
        "type": "string",
        "required": false,
        "description": ""
      },
      {
        "name": "limit",
        "in": "query",
        "type": "string",
        "required": false,
        "description": ""
      }
    ],
    "body_fields": []
  },
  "create_edges_https": {
    "operation_id": "EdgesHttpsCreate",
    "display_name": "Create Edges HTTPS",
    "category": "Edges HTTPS",
    "description": "Create an HTTPS Edge",
    "method": "POST",
    "path": "/edges/https",
    "params": [],
    "body_fields": [
      {
        "name": "description",
        "type": "string",
        "required": false,
        "description": "human-readable description of what this edge will be used for; optional, max 255 bytes."
      },
      {
        "name": "hostports",
        "type": "array",
        "required": false,
        "description": "hostports served by this edge"
      },
      {
        "name": "metadata",
        "type": "string",
        "required": false,
        "description": "arbitrary user-defined machine-readable data of this edge; optional, max 4096 bytes."
      },
      {
        "name": "mutual_tls",
        "type": "object",
        "required": false,
        "description": "edge modules"
      },
      {
        "name": "tls_termination",
        "type": "object",
        "required": false,
        "description": "n/a"
      }
    ]
  },
  "create_edges_https_routes": {
    "operation_id": "EdgesHttpsRoutesCreate",
    "display_name": "Create Edges HTTPS Routes",
    "category": "Edges HTTPS Routes",
    "description": "Create an HTTPS Edge Route",
    "method": "POST",
    "path": "/edges/https/{edge_id}/routes",
    "params": [
      {
        "name": "edge_id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "unique identifier of this edge"
      }
    ],
    "body_fields": [
      {
        "name": "backend",
        "type": "object",
        "required": false,
        "description": "backend module configuration or `null`"
      },
      {
        "name": "circuit_breaker",
        "type": "object",
        "required": false,
        "description": "circuit breaker module configuration or `null`"
      },
      {
        "name": "compression",
        "type": "object",
        "required": false,
        "description": "compression module configuration or `null`"
      },
      {
        "name": "description",
        "type": "string",
        "required": false,
        "description": "human-readable description of what this edge will be used for; optional, max 255 bytes."
      },
      {
        "name": "edge_id",
        "type": "string",
        "required": false,
        "description": "unique identifier of this edge"
      },
      {
        "name": "ip_restriction",
        "type": "object",
        "required": false,
        "description": "ip restriction module configuration or `null`"
      },
      {
        "name": "match",
        "type": "string",
        "required": true,
        "description": "Route selector: \"/blog\" or \"example.com\" or \"example.com/blog\""
      },
      {
        "name": "match_type",
        "type": "string",
        "required": true,
        "description": "Type of match to use for this route. Valid values are \"exact_path\" and \"path_prefix\"."
      },
      {
        "name": "metadata",
        "type": "string",
        "required": false,
        "description": "arbitrary user-defined machine-readable data of this edge. Optional, max 4096 bytes."
      },
      {
        "name": "oauth",
        "type": "object",
        "required": false,
        "description": "oauth module configuration or `null`"
      },
      {
        "name": "oidc",
        "type": "object",
        "required": false,
        "description": "oidc module configuration or `null`"
      },
      {
        "name": "request_headers",
        "type": "object",
        "required": false,
        "description": "request headers module configuration or `null`"
      },
      {
        "name": "response_headers",
        "type": "object",
        "required": false,
        "description": "response headers module configuration or `null`"
      },
      {
        "name": "saml",
        "type": "object",
        "required": false,
        "description": "saml module configuration or `null`"
      },
      {
        "name": "traffic_policy",
        "type": "object",
        "required": false,
        "description": "the traffic policy associated with this edge or null"
      },
      {
        "name": "user_agent_filter",
        "type": "object",
        "required": false,
        "description": "n/a"
      },
      {
        "name": "webhook_verification",
        "type": "object",
        "required": false,
        "description": "webhook verification module configuration or `null`"
      },
      {
        "name": "websocket_tcp_converter",
        "type": "object",
        "required": false,
        "description": "websocket to tcp adapter configuration or `null`"
      }
    ]
  },
  "delete_edges_https_routes": {
    "operation_id": "EdgesHttpsRoutesDelete",
    "display_name": "Delete Edges HTTPS Routes",
    "category": "Edges HTTPS Routes",
    "description": "Delete an HTTPS Edge Route by ID",
    "method": "DELETE",
    "path": "/edges/https/{edge_id}/routes/{id}",
    "params": [
      {
        "name": "edge_id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "unique identifier of this edge"
      },
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "unique identifier of this edge route"
      }
    ],
    "body_fields": []
  },
  "get_edges_https_routes": {
    "operation_id": "EdgesHttpsRoutesGet",
    "display_name": "Get Edges HTTPS Routes",
    "category": "Edges HTTPS Routes",
    "description": "Get an HTTPS Edge Route by ID",
    "method": "GET",
    "path": "/edges/https/{edge_id}/routes/{id}",
    "params": [
      {
        "name": "edge_id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "unique identifier of this edge"
      },
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "unique identifier of this edge route"
      }
    ],
    "body_fields": []
  },
  "update_edges_https_routes": {
    "operation_id": "EdgesHttpsRoutesUpdate",
    "display_name": "Update Edges HTTPS Routes",
    "category": "Edges HTTPS Routes",
    "description": "Updates an HTTPS Edge Route by ID. If a module is not specified in the update, it will not be modified. However, each module configuration that is specified will completely replace the existing value. There is no way to delete an existing module via this API, instead use the delete module API.",
    "method": "PATCH",
    "path": "/edges/https/{edge_id}/routes/{id}",
    "params": [
      {
        "name": "edge_id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "unique identifier of this edge"
      },
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "unique identifier of this edge route"
      }
    ],
    "body_fields": [
      {
        "name": "backend",
        "type": "object",
        "required": false,
        "description": "backend module configuration or `null`"
      },
      {
        "name": "circuit_breaker",
        "type": "object",
        "required": false,
        "description": "circuit breaker module configuration or `null`"
      },
      {
        "name": "compression",
        "type": "object",
        "required": false,
        "description": "compression module configuration or `null`"
      },
      {
        "name": "description",
        "type": "string",
        "required": false,
        "description": "human-readable description of what this edge will be used for; optional, max 255 bytes."
      },
      {
        "name": "edge_id",
        "type": "string",
        "required": false,
        "description": "unique identifier of this edge"
      },
      {
        "name": "id",
        "type": "string",
        "required": false,
        "description": "unique identifier of this edge route"
      },
      {
        "name": "ip_restriction",
        "type": "object",
        "required": false,
        "description": "ip restriction module configuration or `null`"
      },
      {
        "name": "match",
        "type": "string",
        "required": false,
        "description": "Route selector: \"/blog\" or \"example.com\" or \"example.com/blog\""
      },
      {
        "name": "match_type",
        "type": "string",
        "required": false,
        "description": "Type of match to use for this route. Valid values are \"exact_path\" and \"path_prefix\"."
      },
      {
        "name": "metadata",
        "type": "string",
        "required": false,
        "description": "arbitrary user-defined machine-readable data of this edge. Optional, max 4096 bytes."
      },
      {
        "name": "oauth",
        "type": "object",
        "required": false,
        "description": "oauth module configuration or `null`"
      },
      {
        "name": "oidc",
        "type": "object",
        "required": false,
        "description": "oidc module configuration or `null`"
      },
      {
        "name": "request_headers",
        "type": "object",
        "required": false,
        "description": "request headers module configuration or `null`"
      },
      {
        "name": "response_headers",
        "type": "object",
        "required": false,
        "description": "response headers module configuration or `null`"
      },
      {
        "name": "saml",
        "type": "object",
        "required": false,
        "description": "saml module configuration or `null`"
      },
      {
        "name": "traffic_policy",
        "type": "object",
        "required": false,
        "description": "the traffic policy associated with this edge or null"
      },
      {
        "name": "user_agent_filter",
        "type": "object",
        "required": false,
        "description": "n/a"
      },
      {
        "name": "webhook_verification",
        "type": "object",
        "required": false,
        "description": "webhook verification module configuration or `null`"
      },
      {
        "name": "websocket_tcp_converter",
        "type": "object",
        "required": false,
        "description": "websocket to tcp adapter configuration or `null`"
      }
    ]
  },
  "delete_edge_route_backend_module": {
    "operation_id": "EdgeRouteBackendModuleDelete",
    "display_name": "Delete Edge Route Backend Module",
    "category": "Edge Route Backend Module",
    "description": "Delete",
    "method": "DELETE",
    "path": "/edges/https/{edge_id}/routes/{id}/backend",
    "params": [
      {
        "name": "edge_id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "unique identifier of this edge"
      },
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "unique identifier of this edge route"
      }
    ],
    "body_fields": []
  },
  "get_edge_route_backend_module": {
    "operation_id": "EdgeRouteBackendModuleGet",
    "display_name": "Get Edge Route Backend Module",
    "category": "Edge Route Backend Module",
    "description": "Get",
    "method": "GET",
    "path": "/edges/https/{edge_id}/routes/{id}/backend",
    "params": [
      {
        "name": "edge_id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "unique identifier of this edge"
      },
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "unique identifier of this edge route"
      }
    ],
    "body_fields": []
  },
  "replace_edge_route_backend_module": {
    "operation_id": "EdgeRouteBackendModuleReplace",
    "display_name": "Replace Edge Route Backend Module",
    "category": "Edge Route Backend Module",
    "description": "Replace",
    "method": "PUT",
    "path": "/edges/https/{edge_id}/routes/{id}/backend",
    "params": [
      {
        "name": "edge_id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": ""
      },
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": ""
      }
    ],
    "body_fields": [
      {
        "name": "edge_id",
        "type": "string",
        "required": false,
        "description": "n/a"
      },
      {
        "name": "id",
        "type": "string",
        "required": false,
        "description": "n/a"
      },
      {
        "name": "module",
        "type": "object",
        "required": false,
        "description": "n/a"
      }
    ]
  },
  "delete_edge_route_circuit_breaker_module": {
    "operation_id": "EdgeRouteCircuitBreakerModuleDelete",
    "display_name": "Delete Edge Route Circuit Breaker Module",
    "category": "Edge Route Circuit Breaker Module",
    "description": "Delete",
    "method": "DELETE",
    "path": "/edges/https/{edge_id}/routes/{id}/circuit_breaker",
    "params": [
      {
        "name": "edge_id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "unique identifier of this edge"
      },
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "unique identifier of this edge route"
      }
    ],
    "body_fields": []
  },
  "get_edge_route_circuit_breaker_module": {
    "operation_id": "EdgeRouteCircuitBreakerModuleGet",
    "display_name": "Get Edge Route Circuit Breaker Module",
    "category": "Edge Route Circuit Breaker Module",
    "description": "Get",
    "method": "GET",
    "path": "/edges/https/{edge_id}/routes/{id}/circuit_breaker",
    "params": [
      {
        "name": "edge_id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "unique identifier of this edge"
      },
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "unique identifier of this edge route"
      }
    ],
    "body_fields": []
  },
  "replace_edge_route_circuit_breaker_module": {
    "operation_id": "EdgeRouteCircuitBreakerModuleReplace",
    "display_name": "Replace Edge Route Circuit Breaker Module",
    "category": "Edge Route Circuit Breaker Module",
    "description": "Replace",
    "method": "PUT",
    "path": "/edges/https/{edge_id}/routes/{id}/circuit_breaker",
    "params": [
      {
        "name": "edge_id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": ""
      },
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": ""
      }
    ],
    "body_fields": [
      {
        "name": "edge_id",
        "type": "string",
        "required": false,
        "description": "n/a"
      },
      {
        "name": "id",
        "type": "string",
        "required": false,
        "description": "n/a"
      },
      {
        "name": "module",
        "type": "object",
        "required": false,
        "description": "n/a"
      }
    ]
  },
  "delete_edge_route_compression_module": {
    "operation_id": "EdgeRouteCompressionModuleDelete",
    "display_name": "Delete Edge Route Compression Module",
    "category": "Edge Route Compression Module",
    "description": "Delete",
    "method": "DELETE",
    "path": "/edges/https/{edge_id}/routes/{id}/compression",
    "params": [
      {
        "name": "edge_id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "unique identifier of this edge"
      },
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "unique identifier of this edge route"
      }
    ],
    "body_fields": []
  },
  "get_edge_route_compression_module": {
    "operation_id": "EdgeRouteCompressionModuleGet",
    "display_name": "Get Edge Route Compression Module",
    "category": "Edge Route Compression Module",
    "description": "Get",
    "method": "GET",
    "path": "/edges/https/{edge_id}/routes/{id}/compression",
    "params": [
      {
        "name": "edge_id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "unique identifier of this edge"
      },
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "unique identifier of this edge route"
      }
    ],
    "body_fields": []
  },
  "replace_edge_route_compression_module": {
    "operation_id": "EdgeRouteCompressionModuleReplace",
    "display_name": "Replace Edge Route Compression Module",
    "category": "Edge Route Compression Module",
    "description": "Replace",
    "method": "PUT",
    "path": "/edges/https/{edge_id}/routes/{id}/compression",
    "params": [
      {
        "name": "edge_id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": ""
      },
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": ""
      }
    ],
    "body_fields": [
      {
        "name": "edge_id",
        "type": "string",
        "required": false,
        "description": "n/a"
      },
      {
        "name": "id",
        "type": "string",
        "required": false,
        "description": "n/a"
      },
      {
        "name": "module",
        "type": "object",
        "required": false,
        "description": "n/a"
      }
    ]
  },
  "delete_edge_route_ip_restriction_module": {
    "operation_id": "EdgeRouteIpRestrictionModuleDelete",
    "display_name": "Delete Edge Route IP Restriction Module",
    "category": "Edge Route IP Restriction Module",
    "description": "Delete",
    "method": "DELETE",
    "path": "/edges/https/{edge_id}/routes/{id}/ip_restriction",
    "params": [
      {
        "name": "edge_id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "unique identifier of this edge"
      },
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "unique identifier of this edge route"
      }
    ],
    "body_fields": []
  },
  "get_edge_route_ip_restriction_module": {
    "operation_id": "EdgeRouteIpRestrictionModuleGet",
    "display_name": "Get Edge Route IP Restriction Module",
    "category": "Edge Route IP Restriction Module",
    "description": "Get",
    "method": "GET",
    "path": "/edges/https/{edge_id}/routes/{id}/ip_restriction",
    "params": [
      {
        "name": "edge_id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "unique identifier of this edge"
      },
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "unique identifier of this edge route"
      }
    ],
    "body_fields": []
  },
  "replace_edge_route_ip_restriction_module": {
    "operation_id": "EdgeRouteIpRestrictionModuleReplace",
    "display_name": "Replace Edge Route IP Restriction Module",
    "category": "Edge Route IP Restriction Module",
    "description": "Replace",
    "method": "PUT",
    "path": "/edges/https/{edge_id}/routes/{id}/ip_restriction",
    "params": [
      {
        "name": "edge_id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": ""
      },
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": ""
      }
    ],
    "body_fields": [
      {
        "name": "edge_id",
        "type": "string",
        "required": false,
        "description": "n/a"
      },
      {
        "name": "id",
        "type": "string",
        "required": false,
        "description": "n/a"
      },
      {
        "name": "module",
        "type": "object",
        "required": false,
        "description": "n/a"
      }
    ]
  },
  "delete_edge_route_o_auth_module": {
    "operation_id": "EdgeRouteOAuthModuleDelete",
    "display_name": "Delete Edge Route O Auth Module",
    "category": "Edge Route O Auth Module",
    "description": "Delete",
    "method": "DELETE",
    "path": "/edges/https/{edge_id}/routes/{id}/oauth",
    "params": [
      {
        "name": "edge_id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "unique identifier of this edge"
      },
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "unique identifier of this edge route"
      }
    ],
    "body_fields": []
  },
  "get_edge_route_o_auth_module": {
    "operation_id": "EdgeRouteOAuthModuleGet",
    "display_name": "Get Edge Route O Auth Module",
    "category": "Edge Route O Auth Module",
    "description": "Get",
    "method": "GET",
    "path": "/edges/https/{edge_id}/routes/{id}/oauth",
    "params": [
      {
        "name": "edge_id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "unique identifier of this edge"
      },
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "unique identifier of this edge route"
      }
    ],
    "body_fields": []
  },
  "replace_edge_route_o_auth_module": {
    "operation_id": "EdgeRouteOAuthModuleReplace",
    "display_name": "Replace Edge Route O Auth Module",
    "category": "Edge Route O Auth Module",
    "description": "Replace",
    "method": "PUT",
    "path": "/edges/https/{edge_id}/routes/{id}/oauth",
    "params": [
      {
        "name": "edge_id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": ""
      },
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": ""
      }
    ],
    "body_fields": [
      {
        "name": "edge_id",
        "type": "string",
        "required": false,
        "description": "n/a"
      },
      {
        "name": "id",
        "type": "string",
        "required": false,
        "description": "n/a"
      },
      {
        "name": "module",
        "type": "object",
        "required": false,
        "description": "n/a"
      }
    ]
  },
  "delete_edge_route_oidc_module": {
    "operation_id": "EdgeRouteOidcModuleDelete",
    "display_name": "Delete Edge Route OIDC Module",
    "category": "Edge Route OIDC Module",
    "description": "Delete",
    "method": "DELETE",
    "path": "/edges/https/{edge_id}/routes/{id}/oidc",
    "params": [
      {
        "name": "edge_id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "unique identifier of this edge"
      },
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "unique identifier of this edge route"
      }
    ],
    "body_fields": []
  },
  "get_edge_route_oidc_module": {
    "operation_id": "EdgeRouteOidcModuleGet",
    "display_name": "Get Edge Route OIDC Module",
    "category": "Edge Route OIDC Module",
    "description": "Get",
    "method": "GET",
    "path": "/edges/https/{edge_id}/routes/{id}/oidc",
    "params": [
      {
        "name": "edge_id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "unique identifier of this edge"
      },
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "unique identifier of this edge route"
      }
    ],
    "body_fields": []
  },
  "replace_edge_route_oidc_module": {
    "operation_id": "EdgeRouteOidcModuleReplace",
    "display_name": "Replace Edge Route OIDC Module",
    "category": "Edge Route OIDC Module",
    "description": "Replace",
    "method": "PUT",
    "path": "/edges/https/{edge_id}/routes/{id}/oidc",
    "params": [
      {
        "name": "edge_id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": ""
      },
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": ""
      }
    ],
    "body_fields": [
      {
        "name": "edge_id",
        "type": "string",
        "required": false,
        "description": "n/a"
      },
      {
        "name": "id",
        "type": "string",
        "required": false,
        "description": "n/a"
      },
      {
        "name": "module",
        "type": "object",
        "required": false,
        "description": "n/a"
      }
    ]
  },
  "delete_edge_route_request_headers_module": {
    "operation_id": "EdgeRouteRequestHeadersModuleDelete",
    "display_name": "Delete Edge Route Request Headers Module",
    "category": "Edge Route Request Headers Module",
    "description": "Delete",
    "method": "DELETE",
    "path": "/edges/https/{edge_id}/routes/{id}/request_headers",
    "params": [
      {
        "name": "edge_id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "unique identifier of this edge"
      },
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "unique identifier of this edge route"
      }
    ],
    "body_fields": []
  },
  "get_edge_route_request_headers_module": {
    "operation_id": "EdgeRouteRequestHeadersModuleGet",
    "display_name": "Get Edge Route Request Headers Module",
    "category": "Edge Route Request Headers Module",
    "description": "Get",
    "method": "GET",
    "path": "/edges/https/{edge_id}/routes/{id}/request_headers",
    "params": [
      {
        "name": "edge_id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "unique identifier of this edge"
      },
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "unique identifier of this edge route"
      }
    ],
    "body_fields": []
  },
  "replace_edge_route_request_headers_module": {
    "operation_id": "EdgeRouteRequestHeadersModuleReplace",
    "display_name": "Replace Edge Route Request Headers Module",
    "category": "Edge Route Request Headers Module",
    "description": "Replace",
    "method": "PUT",
    "path": "/edges/https/{edge_id}/routes/{id}/request_headers",
    "params": [
      {
        "name": "edge_id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": ""
      },
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": ""
      }
    ],
    "body_fields": [
      {
        "name": "edge_id",
        "type": "string",
        "required": false,
        "description": "n/a"
      },
      {
        "name": "id",
        "type": "string",
        "required": false,
        "description": "n/a"
      },
      {
        "name": "module",
        "type": "object",
        "required": false,
        "description": "n/a"
      }
    ]
  },
  "delete_edge_route_response_headers_module": {
    "operation_id": "EdgeRouteResponseHeadersModuleDelete",
    "display_name": "Delete Edge Route Response Headers Module",
    "category": "Edge Route Response Headers Module",
    "description": "Delete",
    "method": "DELETE",
    "path": "/edges/https/{edge_id}/routes/{id}/response_headers",
    "params": [
      {
        "name": "edge_id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "unique identifier of this edge"
      },
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "unique identifier of this edge route"
      }
    ],
    "body_fields": []
  },
  "get_edge_route_response_headers_module": {
    "operation_id": "EdgeRouteResponseHeadersModuleGet",
    "display_name": "Get Edge Route Response Headers Module",
    "category": "Edge Route Response Headers Module",
    "description": "Get",
    "method": "GET",
    "path": "/edges/https/{edge_id}/routes/{id}/response_headers",
    "params": [
      {
        "name": "edge_id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "unique identifier of this edge"
      },
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "unique identifier of this edge route"
      }
    ],
    "body_fields": []
  },
  "replace_edge_route_response_headers_module": {
    "operation_id": "EdgeRouteResponseHeadersModuleReplace",
    "display_name": "Replace Edge Route Response Headers Module",
    "category": "Edge Route Response Headers Module",
    "description": "Replace",
    "method": "PUT",
    "path": "/edges/https/{edge_id}/routes/{id}/response_headers",
    "params": [
      {
        "name": "edge_id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": ""
      },
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": ""
      }
    ],
    "body_fields": [
      {
        "name": "edge_id",
        "type": "string",
        "required": false,
        "description": "n/a"
      },
      {
        "name": "id",
        "type": "string",
        "required": false,
        "description": "n/a"
      },
      {
        "name": "module",
        "type": "object",
        "required": false,
        "description": "n/a"
      }
    ]
  },
  "delete_edge_route_saml_module": {
    "operation_id": "EdgeRouteSamlModuleDelete",
    "display_name": "Delete Edge Route SAML Module",
    "category": "Edge Route SAML Module",
    "description": "Delete",
    "method": "DELETE",
    "path": "/edges/https/{edge_id}/routes/{id}/saml",
    "params": [
      {
        "name": "edge_id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "unique identifier of this edge"
      },
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "unique identifier of this edge route"
      }
    ],
    "body_fields": []
  },
  "get_edge_route_saml_module": {
    "operation_id": "EdgeRouteSamlModuleGet",
    "display_name": "Get Edge Route SAML Module",
    "category": "Edge Route SAML Module",
    "description": "Get",
    "method": "GET",
    "path": "/edges/https/{edge_id}/routes/{id}/saml",
    "params": [
      {
        "name": "edge_id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "unique identifier of this edge"
      },
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "unique identifier of this edge route"
      }
    ],
    "body_fields": []
  },
  "replace_edge_route_saml_module": {
    "operation_id": "EdgeRouteSamlModuleReplace",
    "display_name": "Replace Edge Route SAML Module",
    "category": "Edge Route SAML Module",
    "description": "Replace",
    "method": "PUT",
    "path": "/edges/https/{edge_id}/routes/{id}/saml",
    "params": [
      {
        "name": "edge_id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": ""
      },
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": ""
      }
    ],
    "body_fields": [
      {
        "name": "edge_id",
        "type": "string",
        "required": false,
        "description": "n/a"
      },
      {
        "name": "id",
        "type": "string",
        "required": false,
        "description": "n/a"
      },
      {
        "name": "module",
        "type": "object",
        "required": false,
        "description": "n/a"
      }
    ]
  },
  "delete_edge_route_traffic_policy_module": {
    "operation_id": "EdgeRouteTrafficPolicyModuleDelete",
    "display_name": "Delete Edge Route Traffic Policy Module",
    "category": "Edge Route Traffic Policy Module",
    "description": "Delete",
    "method": "DELETE",
    "path": "/edges/https/{edge_id}/routes/{id}/traffic_policy",
    "params": [
      {
        "name": "edge_id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "unique identifier of this edge"
      },
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "unique identifier of this edge route"
      }
    ],
    "body_fields": []
  },
  "get_edge_route_traffic_policy_module": {
    "operation_id": "EdgeRouteTrafficPolicyModuleGet",
    "display_name": "Get Edge Route Traffic Policy Module",
    "category": "Edge Route Traffic Policy Module",
    "description": "Get",
    "method": "GET",
    "path": "/edges/https/{edge_id}/routes/{id}/traffic_policy",
    "params": [
      {
        "name": "edge_id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "unique identifier of this edge"
      },
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "unique identifier of this edge route"
      }
    ],
    "body_fields": []
  },
  "replace_edge_route_traffic_policy_module": {
    "operation_id": "EdgeRouteTrafficPolicyModuleReplace",
    "display_name": "Replace Edge Route Traffic Policy Module",
    "category": "Edge Route Traffic Policy Module",
    "description": "Replace",
    "method": "PUT",
    "path": "/edges/https/{edge_id}/routes/{id}/traffic_policy",
    "params": [
      {
        "name": "edge_id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": ""
      },
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": ""
      }
    ],
    "body_fields": [
      {
        "name": "edge_id",
        "type": "string",
        "required": false,
        "description": "n/a"
      },
      {
        "name": "id",
        "type": "string",
        "required": false,
        "description": "n/a"
      },
      {
        "name": "module",
        "type": "object",
        "required": false,
        "description": "n/a"
      }
    ]
  },
  "delete_edge_route_user_agent_filter_module": {
    "operation_id": "EdgeRouteUserAgentFilterModuleDelete",
    "display_name": "Delete Edge Route User Agent Filter Module",
    "category": "Edge Route User Agent Filter Module",
    "description": "Delete",
    "method": "DELETE",
    "path": "/edges/https/{edge_id}/routes/{id}/user_agent_filter",
    "params": [
      {
        "name": "edge_id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "unique identifier of this edge"
      },
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "unique identifier of this edge route"
      }
    ],
    "body_fields": []
  },
  "get_edge_route_user_agent_filter_module": {
    "operation_id": "EdgeRouteUserAgentFilterModuleGet",
    "display_name": "Get Edge Route User Agent Filter Module",
    "category": "Edge Route User Agent Filter Module",
    "description": "Get",
    "method": "GET",
    "path": "/edges/https/{edge_id}/routes/{id}/user_agent_filter",
    "params": [
      {
        "name": "edge_id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "unique identifier of this edge"
      },
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "unique identifier of this edge route"
      }
    ],
    "body_fields": []
  },
  "replace_edge_route_user_agent_filter_module": {
    "operation_id": "EdgeRouteUserAgentFilterModuleReplace",
    "display_name": "Replace Edge Route User Agent Filter Module",
    "category": "Edge Route User Agent Filter Module",
    "description": "Replace",
    "method": "PUT",
    "path": "/edges/https/{edge_id}/routes/{id}/user_agent_filter",
    "params": [
      {
        "name": "edge_id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": ""
      },
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": ""
      }
    ],
    "body_fields": [
      {
        "name": "edge_id",
        "type": "string",
        "required": false,
        "description": "n/a"
      },
      {
        "name": "id",
        "type": "string",
        "required": false,
        "description": "n/a"
      },
      {
        "name": "module",
        "type": "object",
        "required": false,
        "description": "n/a"
      }
    ]
  },
  "delete_edge_route_webhook_verification_module": {
    "operation_id": "EdgeRouteWebhookVerificationModuleDelete",
    "display_name": "Delete Edge Route Webhook Verification Module",
    "category": "Edge Route Webhook Verification Module",
    "description": "Delete",
    "method": "DELETE",
    "path": "/edges/https/{edge_id}/routes/{id}/webhook_verification",
    "params": [
      {
        "name": "edge_id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "unique identifier of this edge"
      },
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "unique identifier of this edge route"
      }
    ],
    "body_fields": []
  },
  "get_edge_route_webhook_verification_module": {
    "operation_id": "EdgeRouteWebhookVerificationModuleGet",
    "display_name": "Get Edge Route Webhook Verification Module",
    "category": "Edge Route Webhook Verification Module",
    "description": "Get",
    "method": "GET",
    "path": "/edges/https/{edge_id}/routes/{id}/webhook_verification",
    "params": [
      {
        "name": "edge_id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "unique identifier of this edge"
      },
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "unique identifier of this edge route"
      }
    ],
    "body_fields": []
  },
  "replace_edge_route_webhook_verification_module": {
    "operation_id": "EdgeRouteWebhookVerificationModuleReplace",
    "display_name": "Replace Edge Route Webhook Verification Module",
    "category": "Edge Route Webhook Verification Module",
    "description": "Replace",
    "method": "PUT",
    "path": "/edges/https/{edge_id}/routes/{id}/webhook_verification",
    "params": [
      {
        "name": "edge_id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": ""
      },
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": ""
      }
    ],
    "body_fields": [
      {
        "name": "edge_id",
        "type": "string",
        "required": false,
        "description": "n/a"
      },
      {
        "name": "id",
        "type": "string",
        "required": false,
        "description": "n/a"
      },
      {
        "name": "module",
        "type": "object",
        "required": false,
        "description": "n/a"
      }
    ]
  },
  "delete_edge_route_websocket_tcp_converter_module": {
    "operation_id": "EdgeRouteWebsocketTcpConverterModuleDelete",
    "display_name": "Delete Edge Route Websocket TCP Converter Module",
    "category": "Edge Route Websocket TCP Converter Module",
    "description": "Delete",
    "method": "DELETE",
    "path": "/edges/https/{edge_id}/routes/{id}/websocket_tcp_converter",
    "params": [
      {
        "name": "edge_id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "unique identifier of this edge"
      },
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "unique identifier of this edge route"
      }
    ],
    "body_fields": []
  },
  "get_edge_route_websocket_tcp_converter_module": {
    "operation_id": "EdgeRouteWebsocketTcpConverterModuleGet",
    "display_name": "Get Edge Route Websocket TCP Converter Module",
    "category": "Edge Route Websocket TCP Converter Module",
    "description": "Get",
    "method": "GET",
    "path": "/edges/https/{edge_id}/routes/{id}/websocket_tcp_converter",
    "params": [
      {
        "name": "edge_id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "unique identifier of this edge"
      },
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "unique identifier of this edge route"
      }
    ],
    "body_fields": []
  },
  "replace_edge_route_websocket_tcp_converter_module": {
    "operation_id": "EdgeRouteWebsocketTcpConverterModuleReplace",
    "display_name": "Replace Edge Route Websocket TCP Converter Module",
    "category": "Edge Route Websocket TCP Converter Module",
    "description": "Replace",
    "method": "PUT",
    "path": "/edges/https/{edge_id}/routes/{id}/websocket_tcp_converter",
    "params": [
      {
        "name": "edge_id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": ""
      },
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": ""
      }
    ],
    "body_fields": [
      {
        "name": "edge_id",
        "type": "string",
        "required": false,
        "description": "n/a"
      },
      {
        "name": "id",
        "type": "string",
        "required": false,
        "description": "n/a"
      },
      {
        "name": "module",
        "type": "object",
        "required": false,
        "description": "n/a"
      }
    ]
  },
  "delete_edges_https": {
    "operation_id": "EdgesHttpsDelete",
    "display_name": "Delete Edges HTTPS",
    "category": "Edges HTTPS",
    "description": "Delete an HTTPS Edge by ID",
    "method": "DELETE",
    "path": "/edges/https/{id}",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "a resource identifier"
      }
    ],
    "body_fields": []
  },
  "get_edges_https": {
    "operation_id": "EdgesHttpsGet",
    "display_name": "Get Edges HTTPS",
    "category": "Edges HTTPS",
    "description": "Get an HTTPS Edge by ID",
    "method": "GET",
    "path": "/edges/https/{id}",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "a resource identifier"
      }
    ],
    "body_fields": []
  },
  "update_edges_https": {
    "operation_id": "EdgesHttpsUpdate",
    "display_name": "Update Edges HTTPS",
    "category": "Edges HTTPS",
    "description": "Updates an HTTPS Edge by ID. If a module is not specified in the update, it will not be modified. However, each module configuration that is specified will completely replace the existing value. There is no way to delete an existing module via this API, instead use the delete module API.",
    "method": "PATCH",
    "path": "/edges/https/{id}",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "unique identifier of this edge"
      }
    ],
    "body_fields": [
      {
        "name": "description",
        "type": "string",
        "required": false,
        "description": "human-readable description of what this edge will be used for; optional, max 255 bytes."
      },
      {
        "name": "hostports",
        "type": "array",
        "required": false,
        "description": "hostports served by this edge"
      },
      {
        "name": "id",
        "type": "string",
        "required": false,
        "description": "unique identifier of this edge"
      },
      {
        "name": "metadata",
        "type": "string",
        "required": false,
        "description": "arbitrary user-defined machine-readable data of this edge; optional, max 4096 bytes."
      },
      {
        "name": "mutual_tls",
        "type": "object",
        "required": false,
        "description": "edge modules"
      },
      {
        "name": "tls_termination",
        "type": "object",
        "required": false,
        "description": "n/a"
      }
    ]
  },
  "delete_https_edge_mutual_tls_module": {
    "operation_id": "HttpsEdgeMutualTlsModuleDelete",
    "display_name": "Delete HTTPS Edge Mutual TLS Module",
    "category": "HTTPS Edge Mutual TLS Module",
    "description": "Delete",
    "method": "DELETE",
    "path": "/edges/https/{id}/mutual_tls",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "a resource identifier"
      }
    ],
    "body_fields": []
  },
  "get_https_edge_mutual_tls_module": {
    "operation_id": "HttpsEdgeMutualTlsModuleGet",
    "display_name": "Get HTTPS Edge Mutual TLS Module",
    "category": "HTTPS Edge Mutual TLS Module",
    "description": "Get",
    "method": "GET",
    "path": "/edges/https/{id}/mutual_tls",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "a resource identifier"
      }
    ],
    "body_fields": []
  },
  "replace_https_edge_mutual_tls_module": {
    "operation_id": "HttpsEdgeMutualTlsModuleReplace",
    "display_name": "Replace HTTPS Edge Mutual TLS Module",
    "category": "HTTPS Edge Mutual TLS Module",
    "description": "Replace",
    "method": "PUT",
    "path": "/edges/https/{id}/mutual_tls",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": ""
      }
    ],
    "body_fields": [
      {
        "name": "id",
        "type": "string",
        "required": false,
        "description": "n/a"
      },
      {
        "name": "module",
        "type": "object",
        "required": false,
        "description": "n/a"
      }
    ]
  },
  "delete_https_edge_tls_termination_module": {
    "operation_id": "HttpsEdgeTlsTerminationModuleDelete",
    "display_name": "Delete HTTPS Edge TLS Termination Module",
    "category": "HTTPS Edge TLS Termination Module",
    "description": "Delete",
    "method": "DELETE",
    "path": "/edges/https/{id}/tls_termination",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "a resource identifier"
      }
    ],
    "body_fields": []
  },
  "get_https_edge_tls_termination_module": {
    "operation_id": "HttpsEdgeTlsTerminationModuleGet",
    "display_name": "Get HTTPS Edge TLS Termination Module",
    "category": "HTTPS Edge TLS Termination Module",
    "description": "Get",
    "method": "GET",
    "path": "/edges/https/{id}/tls_termination",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "a resource identifier"
      }
    ],
    "body_fields": []
  },
  "replace_https_edge_tls_termination_module": {
    "operation_id": "HttpsEdgeTlsTerminationModuleReplace",
    "display_name": "Replace HTTPS Edge TLS Termination Module",
    "category": "HTTPS Edge TLS Termination Module",
    "description": "Replace",
    "method": "PUT",
    "path": "/edges/https/{id}/tls_termination",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": ""
      }
    ],
    "body_fields": [
      {
        "name": "id",
        "type": "string",
        "required": false,
        "description": "n/a"
      },
      {
        "name": "module",
        "type": "object",
        "required": false,
        "description": "n/a"
      }
    ]
  },
  "list_edges_tcp": {
    "operation_id": "EdgesTcpList",
    "display_name": "List Edges TCP",
    "category": "Edges TCP",
    "description": "Returns a list of all TCP Edges on this account",
    "method": "GET",
    "path": "/edges/tcp",
    "params": [
      {
        "name": "before_id",
        "in": "query",
        "type": "string",
        "required": false,
        "description": ""
      },
      {
        "name": "limit",
        "in": "query",
        "type": "string",
        "required": false,
        "description": ""
      }
    ],
    "body_fields": []
  },
  "create_edges_tcp": {
    "operation_id": "EdgesTcpCreate",
    "display_name": "Create Edges TCP",
    "category": "Edges TCP",
    "description": "Create a TCP Edge",
    "method": "POST",
    "path": "/edges/tcp",
    "params": [],
    "body_fields": [
      {
        "name": "backend",
        "type": "object",
        "required": false,
        "description": "edge modules"
      },
      {
        "name": "description",
        "type": "string",
        "required": false,
        "description": "human-readable description of what this edge will be used for; optional, max 255 bytes."
      },
      {
        "name": "hostports",
        "type": "array",
        "required": false,
        "description": "hostports served by this edge"
      },
      {
        "name": "ip_restriction",
        "type": "object",
        "required": false,
        "description": "n/a"
      },
      {
        "name": "metadata",
        "type": "string",
        "required": false,
        "description": "arbitrary user-defined machine-readable data of this edge. Optional, max 4096 bytes."
      },
      {
        "name": "traffic_policy",
        "type": "object",
        "required": false,
        "description": "the traffic policy associated with this edge or null"
      }
    ]
  },
  "delete_edges_tcp": {
    "operation_id": "EdgesTcpDelete",
    "display_name": "Delete Edges TCP",
    "category": "Edges TCP",
    "description": "Delete a TCP Edge by ID",
    "method": "DELETE",
    "path": "/edges/tcp/{id}",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "a resource identifier"
      }
    ],
    "body_fields": []
  },
  "get_edges_tcp": {
    "operation_id": "EdgesTcpGet",
    "display_name": "Get Edges TCP",
    "category": "Edges TCP",
    "description": "Get a TCP Edge by ID",
    "method": "GET",
    "path": "/edges/tcp/{id}",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "a resource identifier"
      }
    ],
    "body_fields": []
  },
  "update_edges_tcp": {
    "operation_id": "EdgesTcpUpdate",
    "display_name": "Update Edges TCP",
    "category": "Edges TCP",
    "description": "Updates a TCP Edge by ID. If a module is not specified in the update, it will not be modified. However, each module configuration that is specified will completely replace the existing value. There is no way to delete an existing module via this API, instead use the delete module API.",
    "method": "PATCH",
    "path": "/edges/tcp/{id}",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "unique identifier of this edge"
      }
    ],
    "body_fields": [
      {
        "name": "backend",
        "type": "object",
        "required": false,
        "description": "edge modules"
      },
      {
        "name": "description",
        "type": "string",
        "required": false,
        "description": "human-readable description of what this edge will be used for; optional, max 255 bytes."
      },
      {
        "name": "hostports",
        "type": "array",
        "required": false,
        "description": "hostports served by this edge"
      },
      {
        "name": "id",
        "type": "string",
        "required": false,
        "description": "unique identifier of this edge"
      },
      {
        "name": "ip_restriction",
        "type": "object",
        "required": false,
        "description": "n/a"
      },
      {
        "name": "metadata",
        "type": "string",
        "required": false,
        "description": "arbitrary user-defined machine-readable data of this edge. Optional, max 4096 bytes."
      },
      {
        "name": "traffic_policy",
        "type": "object",
        "required": false,
        "description": "the traffic policy associated with this edge or null"
      }
    ]
  },
  "delete_tcp_edge_backend_module": {
    "operation_id": "TcpEdgeBackendModuleDelete",
    "display_name": "Delete TCP Edge Backend Module",
    "category": "TCP Edge Backend Module",
    "description": "Delete",
    "method": "DELETE",
    "path": "/edges/tcp/{id}/backend",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "a resource identifier"
      }
    ],
    "body_fields": []
  },
  "get_tcp_edge_backend_module": {
    "operation_id": "TcpEdgeBackendModuleGet",
    "display_name": "Get TCP Edge Backend Module",
    "category": "TCP Edge Backend Module",
    "description": "Get",
    "method": "GET",
    "path": "/edges/tcp/{id}/backend",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "a resource identifier"
      }
    ],
    "body_fields": []
  },
  "replace_tcp_edge_backend_module": {
    "operation_id": "TcpEdgeBackendModuleReplace",
    "display_name": "Replace TCP Edge Backend Module",
    "category": "TCP Edge Backend Module",
    "description": "Replace",
    "method": "PUT",
    "path": "/edges/tcp/{id}/backend",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": ""
      }
    ],
    "body_fields": [
      {
        "name": "id",
        "type": "string",
        "required": false,
        "description": "n/a"
      },
      {
        "name": "module",
        "type": "object",
        "required": false,
        "description": "n/a"
      }
    ]
  },
  "delete_tcp_edge_ip_restriction_module": {
    "operation_id": "TcpEdgeIpRestrictionModuleDelete",
    "display_name": "Delete TCP Edge IP Restriction Module",
    "category": "TCP Edge IP Restriction Module",
    "description": "Delete",
    "method": "DELETE",
    "path": "/edges/tcp/{id}/ip_restriction",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "a resource identifier"
      }
    ],
    "body_fields": []
  },
  "get_tcp_edge_ip_restriction_module": {
    "operation_id": "TcpEdgeIpRestrictionModuleGet",
    "display_name": "Get TCP Edge IP Restriction Module",
    "category": "TCP Edge IP Restriction Module",
    "description": "Get",
    "method": "GET",
    "path": "/edges/tcp/{id}/ip_restriction",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "a resource identifier"
      }
    ],
    "body_fields": []
  },
  "replace_tcp_edge_ip_restriction_module": {
    "operation_id": "TcpEdgeIpRestrictionModuleReplace",
    "display_name": "Replace TCP Edge IP Restriction Module",
    "category": "TCP Edge IP Restriction Module",
    "description": "Replace",
    "method": "PUT",
    "path": "/edges/tcp/{id}/ip_restriction",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": ""
      }
    ],
    "body_fields": [
      {
        "name": "id",
        "type": "string",
        "required": false,
        "description": "n/a"
      },
      {
        "name": "module",
        "type": "object",
        "required": false,
        "description": "n/a"
      }
    ]
  },
  "delete_tcp_edge_traffic_policy_module": {
    "operation_id": "TcpEdgeTrafficPolicyModuleDelete",
    "display_name": "Delete TCP Edge Traffic Policy Module",
    "category": "TCP Edge Traffic Policy Module",
    "description": "Delete",
    "method": "DELETE",
    "path": "/edges/tcp/{id}/traffic_policy",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "a resource identifier"
      }
    ],
    "body_fields": []
  },
  "get_tcp_edge_traffic_policy_module": {
    "operation_id": "TcpEdgeTrafficPolicyModuleGet",
    "display_name": "Get TCP Edge Traffic Policy Module",
    "category": "TCP Edge Traffic Policy Module",
    "description": "Get",
    "method": "GET",
    "path": "/edges/tcp/{id}/traffic_policy",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "a resource identifier"
      }
    ],
    "body_fields": []
  },
  "replace_tcp_edge_traffic_policy_module": {
    "operation_id": "TcpEdgeTrafficPolicyModuleReplace",
    "display_name": "Replace TCP Edge Traffic Policy Module",
    "category": "TCP Edge Traffic Policy Module",
    "description": "Replace",
    "method": "PUT",
    "path": "/edges/tcp/{id}/traffic_policy",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": ""
      }
    ],
    "body_fields": [
      {
        "name": "id",
        "type": "string",
        "required": false,
        "description": "n/a"
      },
      {
        "name": "module",
        "type": "object",
        "required": false,
        "description": "n/a"
      }
    ]
  },
  "list_edges_tls": {
    "operation_id": "EdgesTlsList",
    "display_name": "List Edges TLS",
    "category": "Edges TLS",
    "description": "Returns a list of all TLS Edges on this account",
    "method": "GET",
    "path": "/edges/tls",
    "params": [
      {
        "name": "before_id",
        "in": "query",
        "type": "string",
        "required": false,
        "description": ""
      },
      {
        "name": "limit",
        "in": "query",
        "type": "string",
        "required": false,
        "description": ""
      }
    ],
    "body_fields": []
  },
  "create_edges_tls": {
    "operation_id": "EdgesTlsCreate",
    "display_name": "Create Edges TLS",
    "category": "Edges TLS",
    "description": "Create a TLS Edge",
    "method": "POST",
    "path": "/edges/tls",
    "params": [],
    "body_fields": [
      {
        "name": "backend",
        "type": "object",
        "required": false,
        "description": "edge modules"
      },
      {
        "name": "description",
        "type": "string",
        "required": false,
        "description": "human-readable description of what this edge will be used for; optional, max 255 bytes."
      },
      {
        "name": "hostports",
        "type": "array",
        "required": false,
        "description": "hostports served by this edge"
      },
      {
        "name": "ip_restriction",
        "type": "object",
        "required": false,
        "description": "n/a"
      },
      {
        "name": "metadata",
        "type": "string",
        "required": false,
        "description": "arbitrary user-defined machine-readable data of this edge. Optional, max 4096 bytes."
      },
      {
        "name": "mutual_tls",
        "type": "object",
        "required": false,
        "description": "n/a"
      },
      {
        "name": "tls_termination",
        "type": "object",
        "required": false,
        "description": "n/a"
      },
      {
        "name": "traffic_policy",
        "type": "object",
        "required": false,
        "description": "the traffic policy associated with this edge or null"
      }
    ]
  },
  "delete_edges_tls": {
    "operation_id": "EdgesTlsDelete",
    "display_name": "Delete Edges TLS",
    "category": "Edges TLS",
    "description": "Delete a TLS Edge by ID",
    "method": "DELETE",
    "path": "/edges/tls/{id}",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "a resource identifier"
      }
    ],
    "body_fields": []
  },
  "get_edges_tls": {
    "operation_id": "EdgesTlsGet",
    "display_name": "Get Edges TLS",
    "category": "Edges TLS",
    "description": "Get a TLS Edge by ID",
    "method": "GET",
    "path": "/edges/tls/{id}",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "a resource identifier"
      }
    ],
    "body_fields": []
  },
  "update_edges_tls": {
    "operation_id": "EdgesTlsUpdate",
    "display_name": "Update Edges TLS",
    "category": "Edges TLS",
    "description": "Updates a TLS Edge by ID. If a module is not specified in the update, it will not be modified. However, each module configuration that is specified will completely replace the existing value. There is no way to delete an existing module via this API, instead use the delete module API.",
    "method": "PATCH",
    "path": "/edges/tls/{id}",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "unique identifier of this edge"
      }
    ],
    "body_fields": [
      {
        "name": "backend",
        "type": "object",
        "required": false,
        "description": "edge modules"
      },
      {
        "name": "description",
        "type": "string",
        "required": false,
        "description": "human-readable description of what this edge will be used for; optional, max 255 bytes."
      },
      {
        "name": "hostports",
        "type": "array",
        "required": false,
        "description": "hostports served by this edge"
      },
      {
        "name": "id",
        "type": "string",
        "required": false,
        "description": "unique identifier of this edge"
      },
      {
        "name": "ip_restriction",
        "type": "object",
        "required": false,
        "description": "n/a"
      },
      {
        "name": "metadata",
        "type": "string",
        "required": false,
        "description": "arbitrary user-defined machine-readable data of this edge. Optional, max 4096 bytes."
      },
      {
        "name": "mutual_tls",
        "type": "object",
        "required": false,
        "description": "n/a"
      },
      {
        "name": "tls_termination",
        "type": "object",
        "required": false,
        "description": "n/a"
      },
      {
        "name": "traffic_policy",
        "type": "object",
        "required": false,
        "description": "the traffic policy associated with this edge or null"
      }
    ]
  },
  "delete_tls_edge_backend_module": {
    "operation_id": "TlsEdgeBackendModuleDelete",
    "display_name": "Delete TLS Edge Backend Module",
    "category": "TLS Edge Backend Module",
    "description": "Delete",
    "method": "DELETE",
    "path": "/edges/tls/{id}/backend",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "a resource identifier"
      }
    ],
    "body_fields": []
  },
  "get_tls_edge_backend_module": {
    "operation_id": "TlsEdgeBackendModuleGet",
    "display_name": "Get TLS Edge Backend Module",
    "category": "TLS Edge Backend Module",
    "description": "Get",
    "method": "GET",
    "path": "/edges/tls/{id}/backend",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "a resource identifier"
      }
    ],
    "body_fields": []
  },
  "replace_tls_edge_backend_module": {
    "operation_id": "TlsEdgeBackendModuleReplace",
    "display_name": "Replace TLS Edge Backend Module",
    "category": "TLS Edge Backend Module",
    "description": "Replace",
    "method": "PUT",
    "path": "/edges/tls/{id}/backend",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": ""
      }
    ],
    "body_fields": [
      {
        "name": "id",
        "type": "string",
        "required": false,
        "description": "n/a"
      },
      {
        "name": "module",
        "type": "object",
        "required": false,
        "description": "n/a"
      }
    ]
  },
  "delete_tls_edge_ip_restriction_module": {
    "operation_id": "TlsEdgeIpRestrictionModuleDelete",
    "display_name": "Delete TLS Edge IP Restriction Module",
    "category": "TLS Edge IP Restriction Module",
    "description": "Delete",
    "method": "DELETE",
    "path": "/edges/tls/{id}/ip_restriction",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "a resource identifier"
      }
    ],
    "body_fields": []
  },
  "get_tls_edge_ip_restriction_module": {
    "operation_id": "TlsEdgeIpRestrictionModuleGet",
    "display_name": "Get TLS Edge IP Restriction Module",
    "category": "TLS Edge IP Restriction Module",
    "description": "Get",
    "method": "GET",
    "path": "/edges/tls/{id}/ip_restriction",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "a resource identifier"
      }
    ],
    "body_fields": []
  },
  "replace_tls_edge_ip_restriction_module": {
    "operation_id": "TlsEdgeIpRestrictionModuleReplace",
    "display_name": "Replace TLS Edge IP Restriction Module",
    "category": "TLS Edge IP Restriction Module",
    "description": "Replace",
    "method": "PUT",
    "path": "/edges/tls/{id}/ip_restriction",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": ""
      }
    ],
    "body_fields": [
      {
        "name": "id",
        "type": "string",
        "required": false,
        "description": "n/a"
      },
      {
        "name": "module",
        "type": "object",
        "required": false,
        "description": "n/a"
      }
    ]
  },
  "delete_tls_edge_mutual_tls_module": {
    "operation_id": "TlsEdgeMutualTlsModuleDelete",
    "display_name": "Delete TLS Edge Mutual TLS Module",
    "category": "TLS Edge Mutual TLS Module",
    "description": "Delete",
    "method": "DELETE",
    "path": "/edges/tls/{id}/mutual_tls",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "a resource identifier"
      }
    ],
    "body_fields": []
  },
  "get_tls_edge_mutual_tls_module": {
    "operation_id": "TlsEdgeMutualTlsModuleGet",
    "display_name": "Get TLS Edge Mutual TLS Module",
    "category": "TLS Edge Mutual TLS Module",
    "description": "Get",
    "method": "GET",
    "path": "/edges/tls/{id}/mutual_tls",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "a resource identifier"
      }
    ],
    "body_fields": []
  },
  "replace_tls_edge_mutual_tls_module": {
    "operation_id": "TlsEdgeMutualTlsModuleReplace",
    "display_name": "Replace TLS Edge Mutual TLS Module",
    "category": "TLS Edge Mutual TLS Module",
    "description": "Replace",
    "method": "PUT",
    "path": "/edges/tls/{id}/mutual_tls",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": ""
      }
    ],
    "body_fields": [
      {
        "name": "id",
        "type": "string",
        "required": false,
        "description": "n/a"
      },
      {
        "name": "module",
        "type": "object",
        "required": false,
        "description": "n/a"
      }
    ]
  },
  "delete_tls_edge_tls_termination_module": {
    "operation_id": "TlsEdgeTlsTerminationModuleDelete",
    "display_name": "Delete TLS Edge TLS Termination Module",
    "category": "TLS Edge TLS Termination Module",
    "description": "Delete",
    "method": "DELETE",
    "path": "/edges/tls/{id}/tls_termination",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "a resource identifier"
      }
    ],
    "body_fields": []
  },
  "get_tls_edge_tls_termination_module": {
    "operation_id": "TlsEdgeTlsTerminationModuleGet",
    "display_name": "Get TLS Edge TLS Termination Module",
    "category": "TLS Edge TLS Termination Module",
    "description": "Get",
    "method": "GET",
    "path": "/edges/tls/{id}/tls_termination",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "a resource identifier"
      }
    ],
    "body_fields": []
  },
  "replace_tls_edge_tls_termination_module": {
    "operation_id": "TlsEdgeTlsTerminationModuleReplace",
    "display_name": "Replace TLS Edge TLS Termination Module",
    "category": "TLS Edge TLS Termination Module",
    "description": "Replace",
    "method": "PUT",
    "path": "/edges/tls/{id}/tls_termination",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": ""
      }
    ],
    "body_fields": [
      {
        "name": "id",
        "type": "string",
        "required": false,
        "description": "n/a"
      },
      {
        "name": "module",
        "type": "object",
        "required": false,
        "description": "n/a"
      }
    ]
  },
  "delete_tls_edge_traffic_policy_module": {
    "operation_id": "TlsEdgeTrafficPolicyModuleDelete",
    "display_name": "Delete TLS Edge Traffic Policy Module",
    "category": "TLS Edge Traffic Policy Module",
    "description": "Delete",
    "method": "DELETE",
    "path": "/edges/tls/{id}/traffic_policy",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "a resource identifier"
      }
    ],
    "body_fields": []
  },
  "get_tls_edge_traffic_policy_module": {
    "operation_id": "TlsEdgeTrafficPolicyModuleGet",
    "display_name": "Get TLS Edge Traffic Policy Module",
    "category": "TLS Edge Traffic Policy Module",
    "description": "Get",
    "method": "GET",
    "path": "/edges/tls/{id}/traffic_policy",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "a resource identifier"
      }
    ],
    "body_fields": []
  },
  "replace_tls_edge_traffic_policy_module": {
    "operation_id": "TlsEdgeTrafficPolicyModuleReplace",
    "display_name": "Replace TLS Edge Traffic Policy Module",
    "category": "TLS Edge Traffic Policy Module",
    "description": "Replace",
    "method": "PUT",
    "path": "/edges/tls/{id}/traffic_policy",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": ""
      }
    ],
    "body_fields": [
      {
        "name": "id",
        "type": "string",
        "required": false,
        "description": "n/a"
      },
      {
        "name": "module",
        "type": "object",
        "required": false,
        "description": "n/a"
      }
    ]
  },
  "list_endpoints": {
    "operation_id": "EndpointsList",
    "display_name": "List Endpoints",
    "category": "Endpoints",
    "description": "List all active endpoints on the account",
    "method": "GET",
    "path": "/endpoints",
    "params": [
      {
        "name": "before_id",
        "in": "query",
        "type": "string",
        "required": false,
        "description": "Expects a resource ID as its input. Returns earlier entries in the result set, sorted by ID."
      },
      {
        "name": "limit",
        "in": "query",
        "type": "string",
        "required": false,
        "description": "Constrains the number of results in the dataset. See the [API Overview](https://ngrok.com/docs/api/index#pagination) for details."
      },
      {
        "name": "filter",
        "in": "query",
        "type": "string",
        "required": false,
        "description": "A CEL expression to filter the list results. Supports logical and comparison operators to match on fields such as `id`, `metadata`, `created_at`, and more. See ngrok API Filtering for syntax and field details: https://ngrok.com/docs/api/api-filtering.\nFilterable fields: id, url, type, pooling_enabled, region, scheme, description, metadata, name, created_at, principal.id, bindings"
      }
    ],
    "body_fields": []
  },
  "create_endpoints": {
    "operation_id": "EndpointsCreate",
    "display_name": "Create Endpoints",
    "category": "Endpoints",
    "description": "Create an endpoint, currently available only for cloud endpoints",
    "method": "POST",
    "path": "/endpoints",
    "params": [],
    "body_fields": [
      {
        "name": "bindings",
        "type": "array",
        "required": false,
        "description": "the bindings associated with this endpoint"
      },
      {
        "name": "description",
        "type": "string",
        "required": false,
        "description": "user-supplied description of the associated tunnel"
      },
      {
        "name": "metadata",
        "type": "string",
        "required": false,
        "description": "user-supplied metadata of the associated tunnel or edge object"
      },
      {
        "name": "pooling_enabled",
        "type": "boolean",
        "required": false,
        "description": "n/a"
      },
      {
        "name": "traffic_policy",
        "type": "string",
        "required": true,
        "description": "The traffic policy attached to this endpoint"
      },
      {
        "name": "type",
        "type": "string",
        "required": true,
        "description": "Type of endpoint. Only 'cloud' is currently supported (represents a cloud endpoint). Defaults to 'cloud' if not specified."
      },
      {
        "name": "url",
        "type": "string",
        "required": true,
        "description": "the url of the endpoint"
      }
    ]
  },
  "delete_endpoints": {
    "operation_id": "EndpointsDelete",
    "display_name": "Delete Endpoints",
    "category": "Endpoints",
    "description": "Delete an Endpoint by ID, currently available only for cloud endpoints",
    "method": "DELETE",
    "path": "/endpoints/{id}",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "a resource identifier"
      }
    ],
    "body_fields": []
  },
  "get_endpoints": {
    "operation_id": "EndpointsGet",
    "display_name": "Get Endpoints",
    "category": "Endpoints",
    "description": "Get the status of an endpoint by ID",
    "method": "GET",
    "path": "/endpoints/{id}",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "a resource identifier"
      }
    ],
    "body_fields": []
  },
  "update_endpoints": {
    "operation_id": "EndpointsUpdate",
    "display_name": "Update Endpoints",
    "category": "Endpoints",
    "description": "Update an Endpoint by ID, currently available only for cloud endpoints",
    "method": "PATCH",
    "path": "/endpoints/{id}",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "unique endpoint resource identifier"
      }
    ],
    "body_fields": [
      {
        "name": "bindings",
        "type": "array",
        "required": false,
        "description": "the bindings associated with this endpoint"
      },
      {
        "name": "description",
        "type": "string",
        "required": false,
        "description": "user-supplied description of the associated tunnel"
      },
      {
        "name": "id",
        "type": "string",
        "required": false,
        "description": "unique endpoint resource identifier"
      },
      {
        "name": "metadata",
        "type": "string",
        "required": false,
        "description": "user-supplied metadata of the associated tunnel or edge object"
      },
      {
        "name": "pooling_enabled",
        "type": "boolean",
        "required": false,
        "description": "n/a"
      },
      {
        "name": "traffic_policy",
        "type": "string",
        "required": false,
        "description": "The traffic policy attached to this endpoint"
      },
      {
        "name": "url",
        "type": "string",
        "required": false,
        "description": "the url of the endpoint"
      }
    ]
  },
  "list_event_destinations": {
    "operation_id": "EventDestinationsList",
    "display_name": "List Event Destinations",
    "category": "Event Destinations",
    "description": "List all Event Destinations on this account.",
    "method": "GET",
    "path": "/event_destinations",
    "params": [
      {
        "name": "before_id",
        "in": "query",
        "type": "string",
        "required": false,
        "description": "Expects a resource ID as its input. Returns earlier entries in the result set, sorted by ID."
      },
      {
        "name": "limit",
        "in": "query",
        "type": "string",
        "required": false,
        "description": "Constrains the number of results in the dataset. See the [API Overview](https://ngrok.com/docs/api/index#pagination) for details."
      },
      {
        "name": "filter",
        "in": "query",
        "type": "string",
        "required": false,
        "description": "A CEL expression to filter the list results. Supports logical and comparison operators to match on fields such as `id`, `metadata`, `created_at`, and more. See ngrok API Filtering for syntax and field details: https://ngrok.com/docs/api/api-filtering.\nFilterable fields: id, description, metadata, created_at"
      }
    ],
    "body_fields": []
  },
  "create_event_destinations": {
    "operation_id": "EventDestinationsCreate",
    "display_name": "Create Event Destinations",
    "category": "Event Destinations",
    "description": "Create a new Event Destination. It will not apply to anything until it is associated with an Event Subscription.",
    "method": "POST",
    "path": "/event_destinations",
    "params": [],
    "body_fields": [
      {
        "name": "description",
        "type": "string",
        "required": false,
        "description": "Human-readable description of the Event Destination. Optional, max 255 bytes."
      },
      {
        "name": "format",
        "type": "string",
        "required": false,
        "description": "The output format you would like to serialize events into when sending to their target. Currently the only accepted value is `JSON`."
      },
      {
        "name": "metadata",
        "type": "string",
        "required": false,
        "description": "Arbitrary user-defined machine-readable data of this Event Destination. Optional, max 4096 bytes."
      },
      {
        "name": "target",
        "type": "object",
        "required": false,
        "description": "An object that encapsulates where and how to send your events. An event destination must contain exactly one of the following objects, leaving the rest null: `kinesis`, `firehose`, `cloudwatch_logs`, or `s3`."
      }
    ]
  },
  "delete_event_destinations": {
    "operation_id": "EventDestinationsDelete",
    "display_name": "Delete Event Destinations",
    "category": "Event Destinations",
    "description": "Delete an Event Destination. If the Event Destination is still referenced by an Event Subscription.",
    "method": "DELETE",
    "path": "/event_destinations/{id}",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "a resource identifier"
      }
    ],
    "body_fields": []
  },
  "get_event_destinations": {
    "operation_id": "EventDestinationsGet",
    "display_name": "Get Event Destinations",
    "category": "Event Destinations",
    "description": "Get detailed information about an Event Destination by ID.",
    "method": "GET",
    "path": "/event_destinations/{id}",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "a resource identifier"
      }
    ],
    "body_fields": []
  },
  "update_event_destinations": {
    "operation_id": "EventDestinationsUpdate",
    "display_name": "Update Event Destinations",
    "category": "Event Destinations",
    "description": "Update attributes of an Event Destination.",
    "method": "PATCH",
    "path": "/event_destinations/{id}",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "Unique identifier for this Event Destination."
      }
    ],
    "body_fields": [
      {
        "name": "description",
        "type": "string",
        "required": false,
        "description": "Human-readable description of the Event Destination. Optional, max 255 bytes."
      },
      {
        "name": "format",
        "type": "string",
        "required": false,
        "description": "The output format you would like to serialize events into when sending to their target. Currently the only accepted value is `JSON`."
      },
      {
        "name": "id",
        "type": "string",
        "required": false,
        "description": "Unique identifier for this Event Destination."
      },
      {
        "name": "metadata",
        "type": "string",
        "required": false,
        "description": "Arbitrary user-defined machine-readable data of this Event Destination. Optional, max 4096 bytes."
      },
      {
        "name": "target",
        "type": "object",
        "required": false,
        "description": "An object that encapsulates where and how to send your events. An event destination must contain exactly one of the following objects, leaving the rest null: `kinesis`, `firehose`, `cloudwatch_logs`, or `s3`."
      }
    ]
  },
  "list_event_subscriptions": {
    "operation_id": "EventSubscriptionsList",
    "display_name": "List Event Subscriptions",
    "category": "Event Subscriptions",
    "description": "List this Account's Event Subscriptions.",
    "method": "GET",
    "path": "/event_subscriptions",
    "params": [
      {
        "name": "before_id",
        "in": "query",
        "type": "string",
        "required": false,
        "description": "Expects a resource ID as its input. Returns earlier entries in the result set, sorted by ID."
      },
      {
        "name": "limit",
        "in": "query",
        "type": "string",
        "required": false,
        "description": "Constrains the number of results in the dataset. See the [API Overview](https://ngrok.com/docs/api/index#pagination) for details."
      },
      {
        "name": "filter",
        "in": "query",
        "type": "string",
        "required": false,
        "description": "A CEL expression to filter the list results. Supports logical and comparison operators to match on fields such as `id`, `metadata`, `created_at`, and more. See ngrok API Filtering for syntax and field details: https://ngrok.com/docs/api/api-filtering.\nFilterable fields: id, description, metadata, created_at"
      }
    ],
    "body_fields": []
  },
  "create_event_subscriptions": {
    "operation_id": "EventSubscriptionsCreate",
    "display_name": "Create Event Subscriptions",
    "category": "Event Subscriptions",
    "description": "Create an Event Subscription.",
    "method": "POST",
    "path": "/event_subscriptions",
    "params": [],
    "body_fields": [
      {
        "name": "description",
        "type": "string",
        "required": false,
        "description": "Arbitrary customer supplied information intended to be human readable. Optional, max 255 chars."
      },
      {
        "name": "destination_ids",
        "type": "array",
        "required": false,
        "description": "A list of Event Destination IDs which should be used for this Event Subscription."
      },
      {
        "name": "metadata",
        "type": "string",
        "required": false,
        "description": "Arbitrary customer supplied information intended to be machine readable. Optional, max 4096 chars."
      },
      {
        "name": "sources",
        "type": "array",
        "required": false,
        "description": "Sources containing the types for which this event subscription will trigger"
      }
    ]
  },
  "delete_event_subscriptions": {
    "operation_id": "EventSubscriptionsDelete",
    "display_name": "Delete Event Subscriptions",
    "category": "Event Subscriptions",
    "description": "Delete an Event Subscription.",
    "method": "DELETE",
    "path": "/event_subscriptions/{id}",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "a resource identifier"
      }
    ],
    "body_fields": []
  },
  "get_event_subscriptions": {
    "operation_id": "EventSubscriptionsGet",
    "display_name": "Get Event Subscriptions",
    "category": "Event Subscriptions",
    "description": "Get an Event Subscription by ID.",
    "method": "GET",
    "path": "/event_subscriptions/{id}",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "a resource identifier"
      }
    ],
    "body_fields": []
  },
  "update_event_subscriptions": {
    "operation_id": "EventSubscriptionsUpdate",
    "display_name": "Update Event Subscriptions",
    "category": "Event Subscriptions",
    "description": "Update an Event Subscription.",
    "method": "PATCH",
    "path": "/event_subscriptions/{id}",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "Unique identifier for this Event Subscription."
      }
    ],
    "body_fields": [
      {
        "name": "description",
        "type": "string",
        "required": false,
        "description": "Arbitrary customer supplied information intended to be human readable. Optional, max 255 chars."
      },
      {
        "name": "destination_ids",
        "type": "array",
        "required": false,
        "description": "A list of Event Destination IDs which should be used for this Event Subscription."
      },
      {
        "name": "id",
        "type": "string",
        "required": false,
        "description": "Unique identifier for this Event Subscription."
      },
      {
        "name": "metadata",
        "type": "string",
        "required": false,
        "description": "Arbitrary customer supplied information intended to be machine readable. Optional, max 4096 chars."
      },
      {
        "name": "sources",
        "type": "array",
        "required": false,
        "description": "Sources containing the types for which this event subscription will trigger"
      }
    ]
  },
  "list_event_sources": {
    "operation_id": "EventSourcesList",
    "display_name": "List Event Sources",
    "category": "Event Sources",
    "description": "List the types for which this event subscription will trigger",
    "method": "GET",
    "path": "/event_subscriptions/{subscription_id}/sources",
    "params": [
      {
        "name": "subscription_id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "The unique identifier for the Event Subscription that this Event Source is attached to."
      }
    ],
    "body_fields": []
  },
  "create_event_sources": {
    "operation_id": "EventSourcesCreate",
    "display_name": "Create Event Sources",
    "category": "Event Sources",
    "description": "Add an additional type for which this event subscription will trigger",
    "method": "POST",
    "path": "/event_subscriptions/{subscription_id}/sources",
    "params": [
      {
        "name": "subscription_id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "The unique identifier for the Event Subscription that this Event Source is attached to."
      }
    ],
    "body_fields": [
      {
        "name": "subscription_id",
        "type": "string",
        "required": false,
        "description": "The unique identifier for the Event Subscription that this Event Source is attached to."
      },
      {
        "name": "type",
        "type": "string",
        "required": false,
        "description": "Type of event for which an event subscription will trigger"
      }
    ]
  },
  "delete_event_sources": {
    "operation_id": "EventSourcesDelete",
    "display_name": "Delete Event Sources",
    "category": "Event Sources",
    "description": "Remove a type for which this event subscription will trigger",
    "method": "DELETE",
    "path": "/event_subscriptions/{subscription_id}/sources/{type}",
    "params": [
      {
        "name": "subscription_id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "The unique identifier for the Event Subscription that this Event Source is attached to."
      },
      {
        "name": "type",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "Type of event for which an event subscription will trigger"
      }
    ],
    "body_fields": []
  },
  "get_event_sources": {
    "operation_id": "EventSourcesGet",
    "display_name": "Get Event Sources",
    "category": "Event Sources",
    "description": "Get the details for a given type that triggers for the given event subscription",
    "method": "GET",
    "path": "/event_subscriptions/{subscription_id}/sources/{type}",
    "params": [
      {
        "name": "subscription_id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "The unique identifier for the Event Subscription that this Event Source is attached to."
      },
      {
        "name": "type",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "Type of event for which an event subscription will trigger"
      }
    ],
    "body_fields": []
  },
  "update_event_sources": {
    "operation_id": "EventSourcesUpdate",
    "display_name": "Update Event Sources",
    "category": "Event Sources",
    "description": "Update the type for which this event subscription will trigger",
    "method": "PATCH",
    "path": "/event_subscriptions/{subscription_id}/sources/{type}",
    "params": [
      {
        "name": "subscription_id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "The unique identifier for the Event Subscription that this Event Source is attached to."
      },
      {
        "name": "type",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "Type of event for which an event subscription will trigger"
      }
    ],
    "body_fields": [
      {
        "name": "subscription_id",
        "type": "string",
        "required": false,
        "description": "The unique identifier for the Event Subscription that this Event Source is attached to."
      },
      {
        "name": "type",
        "type": "string",
        "required": false,
        "description": "Type of event for which an event subscription will trigger"
      }
    ]
  },
  "list_ip_policies": {
    "operation_id": "IpPoliciesList",
    "display_name": "List IP Policies",
    "category": "IP Policies",
    "description": "List all IP policies on this account",
    "method": "GET",
    "path": "/ip_policies",
    "params": [
      {
        "name": "before_id",
        "in": "query",
        "type": "string",
        "required": false,
        "description": "Expects a resource ID as its input. Returns earlier entries in the result set, sorted by ID."
      },
      {
        "name": "limit",
        "in": "query",
        "type": "string",
        "required": false,
        "description": "Constrains the number of results in the dataset. See the [API Overview](https://ngrok.com/docs/api/index#pagination) for details."
      },
      {
        "name": "filter",
        "in": "query",
        "type": "string",
        "required": false,
        "description": "A CEL expression to filter the list results. Supports logical and comparison operators to match on fields such as `id`, `metadata`, `created_at`, and more. See ngrok API Filtering for syntax and field details: https://ngrok.com/docs/api/api-filtering.\nFilterable fields: id, created_at, description, metadata, name"
      }
    ],
    "body_fields": []
  },
  "create_ip_policies": {
    "operation_id": "IpPoliciesCreate",
    "display_name": "Create IP Policies",
    "category": "IP Policies",
    "description": "Create a new IP policy. It will not apply to any traffic until you associate to a traffic source via an endpoint configuration or IP restriction.",
    "method": "POST",
    "path": "/ip_policies",
    "params": [],
    "body_fields": [
      {
        "name": "description",
        "type": "string",
        "required": false,
        "description": "human-readable description of the source IPs of this IP policy. optional, max 255 bytes."
      },
      {
        "name": "metadata",
        "type": "string",
        "required": false,
        "description": "arbitrary user-defined machine-readable data of this IP policy. optional, max 4096 bytes."
      }
    ]
  },
  "delete_ip_policies": {
    "operation_id": "IpPoliciesDelete",
    "display_name": "Delete IP Policies",
    "category": "IP Policies",
    "description": "Delete an IP policy. If the IP policy is referenced by another object for the purposes of traffic restriction it will be treated as if the IP policy remains but has zero rules.",
    "method": "DELETE",
    "path": "/ip_policies/{id}",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "a resource identifier"
      }
    ],
    "body_fields": []
  },
  "get_ip_policies": {
    "operation_id": "IpPoliciesGet",
    "display_name": "Get IP Policies",
    "category": "IP Policies",
    "description": "Get detailed information about an IP policy by ID.",
    "method": "GET",
    "path": "/ip_policies/{id}",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "a resource identifier"
      }
    ],
    "body_fields": []
  },
  "update_ip_policies": {
    "operation_id": "IpPoliciesUpdate",
    "display_name": "Update IP Policies",
    "category": "IP Policies",
    "description": "Update attributes of an IP policy by ID",
    "method": "PATCH",
    "path": "/ip_policies/{id}",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": ""
      }
    ],
    "body_fields": [
      {
        "name": "description",
        "type": "string",
        "required": false,
        "description": "human-readable description of the source IPs of this IP policy. optional, max 255 bytes."
      },
      {
        "name": "id",
        "type": "string",
        "required": false,
        "description": "n/a"
      },
      {
        "name": "metadata",
        "type": "string",
        "required": false,
        "description": "arbitrary user-defined machine-readable data of this IP policy. optional, max 4096 bytes."
      }
    ]
  },
  "list_ip_policy_rules": {
    "operation_id": "IpPolicyRulesList",
    "display_name": "List IP Policy Rules",
    "category": "IP Policy Rules",
    "description": "List all IP policy rules on this account",
    "method": "GET",
    "path": "/ip_policy_rules",
    "params": [
      {
        "name": "before_id",
        "in": "query",
        "type": "string",
        "required": false,
        "description": "Expects a resource ID as its input. Returns earlier entries in the result set, sorted by ID."
      },
      {
        "name": "limit",
        "in": "query",
        "type": "string",
        "required": false,
        "description": "Constrains the number of results in the dataset. See the [API Overview](https://ngrok.com/docs/api/index#pagination) for details."
      },
      {
        "name": "filter",
        "in": "query",
        "type": "string",
        "required": false,
        "description": "A CEL expression to filter the list results. Supports logical and comparison operators to match on fields such as `id`, `metadata`, `created_at`, and more. See ngrok API Filtering for syntax and field details: https://ngrok.com/docs/api/api-filtering.\nFilterable fields: id, created_at, description, metadata, cidr, ip_policy_id, action"
      }
    ],
    "body_fields": []
  },
  "create_ip_policy_rules": {
    "operation_id": "IpPolicyRulesCreate",
    "display_name": "Create IP Policy Rules",
    "category": "IP Policy Rules",
    "description": "Create a new IP policy rule attached to an IP Policy.",
    "method": "POST",
    "path": "/ip_policy_rules",
    "params": [],
    "body_fields": [
      {
        "name": "action",
        "type": "string",
        "required": true,
        "description": "the action to apply to the policy rule, either `allow` or `deny`"
      },
      {
        "name": "cidr",
        "type": "string",
        "required": true,
        "description": "an IP or IP range specified in CIDR notation. IPv4 and IPv6 are both supported."
      },
      {
        "name": "description",
        "type": "string",
        "required": false,
        "description": "human-readable description of the source IPs of this IP rule. optional, max 255 bytes."
      },
      {
        "name": "ip_policy_id",
        "type": "string",
        "required": true,
        "description": "ID of the IP policy this IP policy rule will be attached to"
      },
      {
        "name": "metadata",
        "type": "string",
        "required": false,
        "description": "arbitrary user-defined machine-readable data of this IP policy rule. optional, max 4096 bytes."
      }
    ]
  },
  "delete_ip_policy_rules": {
    "operation_id": "IpPolicyRulesDelete",
    "display_name": "Delete IP Policy Rules",
    "category": "IP Policy Rules",
    "description": "Delete an IP policy rule.",
    "method": "DELETE",
    "path": "/ip_policy_rules/{id}",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "a resource identifier"
      }
    ],
    "body_fields": []
  },
  "get_ip_policy_rules": {
    "operation_id": "IpPolicyRulesGet",
    "display_name": "Get IP Policy Rules",
    "category": "IP Policy Rules",
    "description": "Get detailed information about an IP policy rule by ID.",
    "method": "GET",
    "path": "/ip_policy_rules/{id}",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "a resource identifier"
      }
    ],
    "body_fields": []
  },
  "update_ip_policy_rules": {
    "operation_id": "IpPolicyRulesUpdate",
    "display_name": "Update IP Policy Rules",
    "category": "IP Policy Rules",
    "description": "Update attributes of an IP policy rule by ID",
    "method": "PATCH",
    "path": "/ip_policy_rules/{id}",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": ""
      }
    ],
    "body_fields": [
      {
        "name": "cidr",
        "type": "string",
        "required": false,
        "description": "an IP or IP range specified in CIDR notation. IPv4 and IPv6 are both supported."
      },
      {
        "name": "description",
        "type": "string",
        "required": false,
        "description": "human-readable description of the source IPs of this IP rule. optional, max 255 bytes."
      },
      {
        "name": "id",
        "type": "string",
        "required": false,
        "description": "n/a"
      },
      {
        "name": "metadata",
        "type": "string",
        "required": false,
        "description": "arbitrary user-defined machine-readable data of this IP policy rule. optional, max 4096 bytes."
      }
    ]
  },
  "list_ip_restrictions": {
    "operation_id": "IpRestrictionsList",
    "display_name": "List IP Restrictions",
    "category": "IP Restrictions",
    "description": "List all IP restrictions on this account",
    "method": "GET",
    "path": "/ip_restrictions",
    "params": [
      {
        "name": "before_id",
        "in": "query",
        "type": "string",
        "required": false,
        "description": "Expects a resource ID as its input. Returns earlier entries in the result set, sorted by ID."
      },
      {
        "name": "limit",
        "in": "query",
        "type": "string",
        "required": false,
        "description": "Constrains the number of results in the dataset. See the [API Overview](https://ngrok.com/docs/api/index#pagination) for details."
      },
      {
        "name": "filter",
        "in": "query",
        "type": "string",
        "required": false,
        "description": "A CEL expression to filter the list results. Supports logical and comparison operators to match on fields such as `id`, `metadata`, `created_at`, and more. See ngrok API Filtering for syntax and field details: https://ngrok.com/docs/api/api-filtering.\nFilterable fields: id, created_at, description, metadata"
      }
    ],
    "body_fields": []
  },
  "create_ip_restrictions": {
    "operation_id": "IpRestrictionsCreate",
    "display_name": "Create IP Restrictions",
    "category": "IP Restrictions",
    "description": "Create a new IP restriction",
    "method": "POST",
    "path": "/ip_restrictions",
    "params": [],
    "body_fields": [
      {
        "name": "description",
        "type": "string",
        "required": false,
        "description": "human-readable description of this IP restriction. optional, max 255 bytes."
      },
      {
        "name": "enforced",
        "type": "boolean",
        "required": false,
        "description": "true if the IP restriction will be enforced. if false, only warnings will be issued"
      },
      {
        "name": "ip_policy_ids",
        "type": "array",
        "required": true,
        "description": "the set of IP policy identifiers that are used to enforce the restriction"
      },
      {
        "name": "metadata",
        "type": "string",
        "required": false,
        "description": "arbitrary user-defined machine-readable data of this IP restriction. optional, max 4096 bytes."
      },
      {
        "name": "type",
        "type": "string",
        "required": true,
        "description": "the type of IP restriction. this defines what traffic will be restricted with the attached policies. four values are currently supported: `dashboard`, `api`, `agent`, and `endpoints`"
      }
    ]
  },
  "delete_ip_restrictions": {
    "operation_id": "IpRestrictionsDelete",
    "display_name": "Delete IP Restrictions",
    "category": "IP Restrictions",
    "description": "Delete an IP restriction",
    "method": "DELETE",
    "path": "/ip_restrictions/{id}",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "a resource identifier"
      }
    ],
    "body_fields": []
  },
  "get_ip_restrictions": {
    "operation_id": "IpRestrictionsGet",
    "display_name": "Get IP Restrictions",
    "category": "IP Restrictions",
    "description": "Get detailed information about an IP restriction",
    "method": "GET",
    "path": "/ip_restrictions/{id}",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "a resource identifier"
      }
    ],
    "body_fields": []
  },
  "update_ip_restrictions": {
    "operation_id": "IpRestrictionsUpdate",
    "display_name": "Update IP Restrictions",
    "category": "IP Restrictions",
    "description": "Update attributes of an IP restriction by ID",
    "method": "PATCH",
    "path": "/ip_restrictions/{id}",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": ""
      }
    ],
    "body_fields": [
      {
        "name": "description",
        "type": "string",
        "required": false,
        "description": "human-readable description of this IP restriction. optional, max 255 bytes."
      },
      {
        "name": "enforced",
        "type": "boolean",
        "required": false,
        "description": "true if the IP restriction will be enforced. if false, only warnings will be issued"
      },
      {
        "name": "id",
        "type": "string",
        "required": false,
        "description": "n/a"
      },
      {
        "name": "ip_policy_ids",
        "type": "array",
        "required": false,
        "description": "the set of IP policy identifiers that are used to enforce the restriction"
      },
      {
        "name": "metadata",
        "type": "string",
        "required": false,
        "description": "arbitrary user-defined machine-readable data of this IP restriction. optional, max 4096 bytes."
      }
    ]
  },
  "list_reserved_addrs": {
    "operation_id": "ReservedAddrsList",
    "display_name": "List Reserved Addrs",
    "category": "Reserved Addrs",
    "description": "List all reserved addresses on this account.",
    "method": "GET",
    "path": "/reserved_addrs",
    "params": [
      {
        "name": "before_id",
        "in": "query",
        "type": "string",
        "required": false,
        "description": "Expects a resource ID as its input. Returns earlier entries in the result set, sorted by ID."
      },
      {
        "name": "limit",
        "in": "query",
        "type": "string",
        "required": false,
        "description": "Constrains the number of results in the dataset. See the [API Overview](https://ngrok.com/docs/api/index#pagination) for details."
      },
      {
        "name": "filter",
        "in": "query",
        "type": "string",
        "required": false,
        "description": "A CEL expression to filter the list results. Supports logical and comparison operators to match on fields such as `id`, `metadata`, `created_at`, and more. See ngrok API Filtering for syntax and field details: https://ngrok.com/docs/api/api-filtering.\nFilterable fields: id, description, metadata, addr, region, created_at"
      }
    ],
    "body_fields": []
  },
  "create_reserved_addrs": {
    "operation_id": "ReservedAddrsCreate",
    "display_name": "Create Reserved Addrs",
    "category": "Reserved Addrs",
    "description": "Create a new reserved address.",
    "method": "POST",
    "path": "/reserved_addrs",
    "params": [],
    "body_fields": [
      {
        "name": "description",
        "type": "string",
        "required": false,
        "description": "human-readable description of what this reserved address will be used for"
      },
      {
        "name": "metadata",
        "type": "string",
        "required": false,
        "description": "arbitrary user-defined machine-readable data of this reserved address. Optional, max 4096 bytes."
      },
      {
        "name": "region",
        "type": "string",
        "required": false,
        "description": "reserve the address in this geographic ngrok datacenter. Optional, default is us. (au, eu, ap, us, jp, in, sa)"
      }
    ]
  },
  "delete_reserved_addrs": {
    "operation_id": "ReservedAddrsDelete",
    "display_name": "Delete Reserved Addrs",
    "category": "Reserved Addrs",
    "description": "Delete a reserved address.",
    "method": "DELETE",
    "path": "/reserved_addrs/{id}",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "a resource identifier"
      }
    ],
    "body_fields": []
  },
  "get_reserved_addrs": {
    "operation_id": "ReservedAddrsGet",
    "display_name": "Get Reserved Addrs",
    "category": "Reserved Addrs",
    "description": "Get the details of a reserved address.",
    "method": "GET",
    "path": "/reserved_addrs/{id}",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "a resource identifier"
      }
    ],
    "body_fields": []
  },
  "update_reserved_addrs": {
    "operation_id": "ReservedAddrsUpdate",
    "display_name": "Update Reserved Addrs",
    "category": "Reserved Addrs",
    "description": "Update the attributes of a reserved address.",
    "method": "PATCH",
    "path": "/reserved_addrs/{id}",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": ""
      }
    ],
    "body_fields": [
      {
        "name": "description",
        "type": "string",
        "required": false,
        "description": "human-readable description of what this reserved address will be used for"
      },
      {
        "name": "id",
        "type": "string",
        "required": false,
        "description": "n/a"
      },
      {
        "name": "metadata",
        "type": "string",
        "required": false,
        "description": "arbitrary user-defined machine-readable data of this reserved address. Optional, max 4096 bytes."
      }
    ]
  },
  "list_reserved_domains": {
    "operation_id": "ReservedDomainsList",
    "display_name": "List Reserved Domains",
    "category": "Reserved Domains",
    "description": "List all reserved domains on this account.",
    "method": "GET",
    "path": "/reserved_domains",
    "params": [
      {
        "name": "before_id",
        "in": "query",
        "type": "string",
        "required": false,
        "description": "Expects a resource ID as its input. Returns earlier entries in the result set, sorted by ID."
      },
      {
        "name": "limit",
        "in": "query",
        "type": "string",
        "required": false,
        "description": "Constrains the number of results in the dataset. See the [API Overview](https://ngrok.com/docs/api/index#pagination) for details."
      },
      {
        "name": "filter",
        "in": "query",
        "type": "string",
        "required": false,
        "description": "A CEL expression to filter the list results. Supports logical and comparison operators to match on fields such as `id`, `metadata`, `created_at`, and more. See ngrok API Filtering for syntax and field details: https://ngrok.com/docs/api/api-filtering.\nFilterable fields: id, description, metadata, domain, created_at"
      }
    ],
    "body_fields": []
  },
  "create_reserved_domains": {
    "operation_id": "ReservedDomainsCreate",
    "display_name": "Create Reserved Domains",
    "category": "Reserved Domains",
    "description": "Create a new reserved domain.",
    "method": "POST",
    "path": "/reserved_domains",
    "params": [],
    "body_fields": [
      {
        "name": "certificate_id",
        "type": "string",
        "required": false,
        "description": "ID of a user-uploaded TLS certificate to use for connections to targeting this domain. Optional, mutually exclusive with `certificate_management_policy`."
      },
      {
        "name": "certificate_management_policy",
        "type": "object",
        "required": false,
        "description": "configuration for automatic management of TLS certificates for this domain, or null if automatic management is disabled. Optional, mutually exclusive with `certificate_id`."
      },
      {
        "name": "description",
        "type": "string",
        "required": false,
        "description": "human-readable description of what this reserved domain will be used for"
      },
      {
        "name": "domain",
        "type": "string",
        "required": false,
        "description": "hostname of the reserved domain"
      },
      {
        "name": "metadata",
        "type": "string",
        "required": false,
        "description": "arbitrary user-defined machine-readable data of this reserved domain. Optional, max 4096 bytes."
      },
      {
        "name": "region",
        "type": "string",
        "required": false,
        "description": "deprecated: With the launch of the ngrok Global Network domains traffic is now handled globally. This field applied only to endpoints. Note that agents may still connect to specific regions. Optional, null by default. (au, eu, ap, us, jp, in, sa)"
      },
      {
        "name": "resolves_to",
        "type": "array",
        "required": false,
        "description": "Region and IP resolution targets configured for the Domain."
      }
    ]
  },
  "delete_reserved_domains": {
    "operation_id": "ReservedDomainsDelete",
    "display_name": "Delete Reserved Domains",
    "category": "Reserved Domains",
    "description": "Delete a reserved domain.",
    "method": "DELETE",
    "path": "/reserved_domains/{id}",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "a resource identifier"
      }
    ],
    "body_fields": []
  },
  "get_reserved_domains": {
    "operation_id": "ReservedDomainsGet",
    "display_name": "Get Reserved Domains",
    "category": "Reserved Domains",
    "description": "Get the details of a reserved domain.",
    "method": "GET",
    "path": "/reserved_domains/{id}",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "a resource identifier"
      }
    ],
    "body_fields": []
  },
  "update_reserved_domains": {
    "operation_id": "ReservedDomainsUpdate",
    "display_name": "Update Reserved Domains",
    "category": "Reserved Domains",
    "description": "Update the attributes of a reserved domain.",
    "method": "PATCH",
    "path": "/reserved_domains/{id}",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": ""
      }
    ],
    "body_fields": [
      {
        "name": "certificate_id",
        "type": "string",
        "required": false,
        "description": "ID of a user-uploaded TLS certificate to use for connections to targeting this domain. Optional, mutually exclusive with `certificate_management_policy`."
      },
      {
        "name": "certificate_management_policy",
        "type": "object",
        "required": false,
        "description": "configuration for automatic management of TLS certificates for this domain, or null if automatic management is disabled. Optional, mutually exclusive with `certificate_id`."
      },
      {
        "name": "description",
        "type": "string",
        "required": false,
        "description": "human-readable description of what this reserved domain will be used for"
      },
      {
        "name": "id",
        "type": "string",
        "required": false,
        "description": "n/a"
      },
      {
        "name": "metadata",
        "type": "string",
        "required": false,
        "description": "arbitrary user-defined machine-readable data of this reserved domain. Optional, max 4096 bytes."
      },
      {
        "name": "resolves_to",
        "type": "array",
        "required": false,
        "description": "Region and IP resolution targets configured for the Domain."
      }
    ]
  },
  "reserved_domains_delete_certificate": {
    "operation_id": "ReservedDomainsDeleteCertificate",
    "display_name": "Reserved Domains Delete Certificate",
    "category": "Reserved Domains",
    "description": "Detach the certificate attached to a reserved domain.",
    "method": "DELETE",
    "path": "/reserved_domains/{id}/certificate",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "a resource identifier"
      }
    ],
    "body_fields": []
  },
  "reserved_domains_delete_certificate_management_policy": {
    "operation_id": "ReservedDomainsDeleteCertificateManagementPolicy",
    "display_name": "Reserved Domains Delete Certificate Management Policy",
    "category": "Reserved Domains",
    "description": "Detach the certificate management policy attached to a reserved domain.",
    "method": "DELETE",
    "path": "/reserved_domains/{id}/certificate_management_policy",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "a resource identifier"
      }
    ],
    "body_fields": []
  },
  "list_service_users": {
    "operation_id": "ServiceUsersList",
    "display_name": "List Service Users",
    "category": "Service Users",
    "description": "List all service users in this account.",
    "method": "GET",
    "path": "/service_users",
    "params": [
      {
        "name": "before_id",
        "in": "query",
        "type": "string",
        "required": false,
        "description": "Expects a resource ID as its input. Returns earlier entries in the result set, sorted by ID."
      },
      {
        "name": "limit",
        "in": "query",
        "type": "string",
        "required": false,
        "description": "Constrains the number of results in the dataset. See the [API Overview](https://ngrok.com/docs/api/index#pagination) for details."
      },
      {
        "name": "filter",
        "in": "query",
        "type": "string",
        "required": false,
        "description": "A CEL expression to filter the list results. Supports logical and comparison operators to match on fields such as `id`, `metadata`, `created_at`, and more. See ngrok API Filtering for syntax and field details: https://ngrok.com/docs/api/api-filtering.\nFilterable fields: id, name, created_at"
      }
    ],
    "body_fields": []
  },
  "create_service_users": {
    "operation_id": "ServiceUsersCreate",
    "display_name": "Create Service Users",
    "category": "Service Users",
    "description": "Create a new service user",
    "method": "POST",
    "path": "/service_users",
    "params": [],
    "body_fields": [
      {
        "name": "active",
        "type": "boolean",
        "required": false,
        "description": "whether or not the service is active"
      },
      {
        "name": "name",
        "type": "string",
        "required": false,
        "description": "human-readable name used to identify the service"
      }
    ]
  },
  "delete_service_users": {
    "operation_id": "ServiceUsersDelete",
    "display_name": "Delete Service Users",
    "category": "Service Users",
    "description": "Delete a service user by ID",
    "method": "DELETE",
    "path": "/service_users/{id}",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "a resource identifier"
      }
    ],
    "body_fields": []
  },
  "get_service_users": {
    "operation_id": "ServiceUsersGet",
    "display_name": "Get Service Users",
    "category": "Service Users",
    "description": "Get the details of a Bot User by ID.",
    "method": "GET",
    "path": "/service_users/{id}",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "a resource identifier"
      }
    ],
    "body_fields": []
  },
  "update_service_users": {
    "operation_id": "ServiceUsersUpdate",
    "display_name": "Update Service Users",
    "category": "Service Users",
    "description": "Update attributes of a service user by ID.",
    "method": "PATCH",
    "path": "/service_users/{id}",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": ""
      }
    ],
    "body_fields": [
      {
        "name": "active",
        "type": "boolean",
        "required": false,
        "description": "whether or not the service is active"
      },
      {
        "name": "id",
        "type": "string",
        "required": false,
        "description": "n/a"
      },
      {
        "name": "name",
        "type": "string",
        "required": false,
        "description": "human-readable name used to identify the service"
      }
    ]
  },
  "list_ssh_certificate_authorities": {
    "operation_id": "SshCertificateAuthoritiesList",
    "display_name": "List SSH Certificate Authorities",
    "category": "SSH Certificate Authorities",
    "description": "List all SSH Certificate Authorities on this account",
    "method": "GET",
    "path": "/ssh_certificate_authorities",
    "params": [
      {
        "name": "before_id",
        "in": "query",
        "type": "string",
        "required": false,
        "description": "Expects a resource ID as its input. Returns earlier entries in the result set, sorted by ID."
      },
      {
        "name": "limit",
        "in": "query",
        "type": "string",
        "required": false,
        "description": "Constrains the number of results in the dataset. See the [API Overview](https://ngrok.com/docs/api/index#pagination) for details."
      },
      {
        "name": "filter",
        "in": "query",
        "type": "string",
        "required": false,
        "description": "A CEL expression to filter the list results. Supports logical and comparison operators to match on fields such as `id`, `metadata`, `created_at`, and more. See ngrok API Filtering for syntax and field details: https://ngrok.com/docs/api/api-filtering.\nFilterable fields: id, created_at, description, metadata"
      }
    ],
    "body_fields": []
  },
  "create_ssh_certificate_authorities": {
    "operation_id": "SshCertificateAuthoritiesCreate",
    "display_name": "Create SSH Certificate Authorities",
    "category": "SSH Certificate Authorities",
    "description": "Create a new SSH Certificate Authority",
    "method": "POST",
    "path": "/ssh_certificate_authorities",
    "params": [],
    "body_fields": [
      {
        "name": "description",
        "type": "string",
        "required": false,
        "description": "human-readable description of this SSH Certificate Authority. optional, max 255 bytes."
      },
      {
        "name": "elliptic_curve",
        "type": "string",
        "required": false,
        "description": "the type of elliptic curve to use when creating an ECDSA key"
      },
      {
        "name": "key_size",
        "type": "integer",
        "required": false,
        "description": "the key size to use when creating an RSA key. one of `2048` or `4096`"
      },
      {
        "name": "metadata",
        "type": "string",
        "required": false,
        "description": "arbitrary user-defined machine-readable data of this SSH Certificate Authority. optional, max 4096 bytes."
      },
      {
        "name": "private_key_type",
        "type": "string",
        "required": false,
        "description": "the type of private key to generate. one of `rsa`, `ecdsa`, `ed25519`"
      }
    ]
  },
  "delete_ssh_certificate_authorities": {
    "operation_id": "SshCertificateAuthoritiesDelete",
    "display_name": "Delete SSH Certificate Authorities",
    "category": "SSH Certificate Authorities",
    "description": "Delete an SSH Certificate Authority",
    "method": "DELETE",
    "path": "/ssh_certificate_authorities/{id}",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "a resource identifier"
      }
    ],
    "body_fields": []
  },
  "get_ssh_certificate_authorities": {
    "operation_id": "SshCertificateAuthoritiesGet",
    "display_name": "Get SSH Certificate Authorities",
    "category": "SSH Certificate Authorities",
    "description": "Get detailed information about an SSH Certificate Authority",
    "method": "GET",
    "path": "/ssh_certificate_authorities/{id}",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "a resource identifier"
      }
    ],
    "body_fields": []
  },
  "update_ssh_certificate_authorities": {
    "operation_id": "SshCertificateAuthoritiesUpdate",
    "display_name": "Update SSH Certificate Authorities",
    "category": "SSH Certificate Authorities",
    "description": "Update an SSH Certificate Authority",
    "method": "PATCH",
    "path": "/ssh_certificate_authorities/{id}",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": ""
      }
    ],
    "body_fields": [
      {
        "name": "description",
        "type": "string",
        "required": false,
        "description": "human-readable description of this SSH Certificate Authority. optional, max 255 bytes."
      },
      {
        "name": "id",
        "type": "string",
        "required": false,
        "description": "n/a"
      },
      {
        "name": "metadata",
        "type": "string",
        "required": false,
        "description": "arbitrary user-defined machine-readable data of this SSH Certificate Authority. optional, max 4096 bytes."
      }
    ]
  },
  "list_ssh_credentials": {
    "operation_id": "SshCredentialsList",
    "display_name": "List SSH Credentials",
    "category": "SSH Credentials",
    "description": "List all ssh credentials on this account",
    "method": "GET",
    "path": "/ssh_credentials",
    "params": [
      {
        "name": "before_id",
        "in": "query",
        "type": "string",
        "required": false,
        "description": "Expects a resource ID as its input. Returns earlier entries in the result set, sorted by ID."
      },
      {
        "name": "limit",
        "in": "query",
        "type": "string",
        "required": false,
        "description": "Constrains the number of results in the dataset. See the [API Overview](https://ngrok.com/docs/api/index#pagination) for details."
      },
      {
        "name": "filter",
        "in": "query",
        "type": "string",
        "required": false,
        "description": "A CEL expression to filter the list results. Supports logical and comparison operators to match on fields such as `id`, `metadata`, `created_at`, and more. See ngrok API Filtering for syntax and field details: https://ngrok.com/docs/api/api-filtering.\nFilterable fields: id, description, metadata, owner_id, acl, created_at"
      }
    ],
    "body_fields": []
  },
  "create_ssh_credentials": {
    "operation_id": "SshCredentialsCreate",
    "display_name": "Create SSH Credentials",
    "category": "SSH Credentials",
    "description": "Create a new ssh_credential from an uploaded public SSH key. This ssh credential can be used to start new tunnels via ngrok's SSH gateway.",
    "method": "POST",
    "path": "/ssh_credentials",
    "params": [],
    "body_fields": [
      {
        "name": "acl",
        "type": "array",
        "required": false,
        "description": "optional list of ACL rules. If unspecified, the credential will have no restrictions. The only allowed ACL rule at this time is the `bind` rule. The `bind` rule allows the caller to restrict what domains, addresses, and labels the token is allowed to bind. For example, to allow the token to open a tunnel on example.ngrok.io your ACL would include the rule `bind:example.ngrok.io`. Bind rules for domains may specify a leading wildcard to match multiple domains with a common suffix. For example, you may specify a rule of `bind:*.example.com` which will allow `x.example.com`, `y.example.com`, `*.example.com`, etc. Bind rules for labels may specify a wildcard key and/or value to match multiple labels. For example, you may specify a rule of `bind:*=example` which will allow `x=example`, `y=example`, etc. A rule of `'*'` is equivalent to no acl at all and will explicitly permit all actions."
      },
      {
        "name": "description",
        "type": "string",
        "required": false,
        "description": "human-readable description of who or what will use the ssh credential to authenticate. Optional, max 255 bytes."
      },
      {
        "name": "metadata",
        "type": "string",
        "required": false,
        "description": "arbitrary user-defined machine-readable data of this ssh credential. Optional, max 4096 bytes."
      },
      {
        "name": "owner_id",
        "type": "string",
        "required": false,
        "description": "If supplied at credential creation, ownership will be assigned to the specified User or Bot. Only admins may specify an owner other than themselves. Defaults to the authenticated User or Bot."
      },
      {
        "name": "public_key",
        "type": "string",
        "required": true,
        "description": "the PEM-encoded public key of the SSH keypair that will be used to authenticate"
      }
    ]
  },
  "delete_ssh_credentials": {
    "operation_id": "SshCredentialsDelete",
    "display_name": "Delete SSH Credentials",
    "category": "SSH Credentials",
    "description": "Delete an ssh_credential by ID",
    "method": "DELETE",
    "path": "/ssh_credentials/{id}",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "a resource identifier"
      }
    ],
    "body_fields": []
  },
  "get_ssh_credentials": {
    "operation_id": "SshCredentialsGet",
    "display_name": "Get SSH Credentials",
    "category": "SSH Credentials",
    "description": "Get detailed information about an ssh_credential",
    "method": "GET",
    "path": "/ssh_credentials/{id}",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "a resource identifier"
      }
    ],
    "body_fields": []
  },
  "update_ssh_credentials": {
    "operation_id": "SshCredentialsUpdate",
    "display_name": "Update SSH Credentials",
    "category": "SSH Credentials",
    "description": "Update attributes of an ssh_credential by ID",
    "method": "PATCH",
    "path": "/ssh_credentials/{id}",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": ""
      }
    ],
    "body_fields": [
      {
        "name": "acl",
        "type": "array",
        "required": false,
        "description": "optional list of ACL rules. If unspecified, the credential will have no restrictions. The only allowed ACL rule at this time is the `bind` rule. The `bind` rule allows the caller to restrict what domains, addresses, and labels the token is allowed to bind. For example, to allow the token to open a tunnel on example.ngrok.io your ACL would include the rule `bind:example.ngrok.io`. Bind rules for domains may specify a leading wildcard to match multiple domains with a common suffix. For example, you may specify a rule of `bind:*.example.com` which will allow `x.example.com`, `y.example.com`, `*.example.com`, etc. Bind rules for labels may specify a wildcard key and/or value to match multiple labels. For example, you may specify a rule of `bind:*=example` which will allow `x=example`, `y=example`, etc. A rule of `'*'` is equivalent to no acl at all and will explicitly permit all actions."
      },
      {
        "name": "description",
        "type": "string",
        "required": false,
        "description": "human-readable description of who or what will use the ssh credential to authenticate. Optional, max 255 bytes."
      },
      {
        "name": "id",
        "type": "string",
        "required": false,
        "description": "n/a"
      },
      {
        "name": "metadata",
        "type": "string",
        "required": false,
        "description": "arbitrary user-defined machine-readable data of this ssh credential. Optional, max 4096 bytes."
      }
    ]
  },
  "list_ssh_host_certificates": {
    "operation_id": "SshHostCertificatesList",
    "display_name": "List SSH Host Certificates",
    "category": "SSH Host Certificates",
    "description": "List all SSH Host Certificates issued on this account",
    "method": "GET",
    "path": "/ssh_host_certificates",
    "params": [
      {
        "name": "before_id",
        "in": "query",
        "type": "string",
        "required": false,
        "description": ""
      },
      {
        "name": "limit",
        "in": "query",
        "type": "string",
        "required": false,
        "description": ""
      }
    ],
    "body_fields": []
  },
  "create_ssh_host_certificates": {
    "operation_id": "SshHostCertificatesCreate",
    "display_name": "Create SSH Host Certificates",
    "category": "SSH Host Certificates",
    "description": "Create a new SSH Host Certificate",
    "method": "POST",
    "path": "/ssh_host_certificates",
    "params": [],
    "body_fields": [
      {
        "name": "description",
        "type": "string",
        "required": false,
        "description": "human-readable description of this SSH Host Certificate. optional, max 255 bytes."
      },
      {
        "name": "metadata",
        "type": "string",
        "required": false,
        "description": "arbitrary user-defined machine-readable data of this SSH Host Certificate. optional, max 4096 bytes."
      },
      {
        "name": "principals",
        "type": "array",
        "required": false,
        "description": "the list of principals included in the ssh host certificate. This is the list of hostnames and/or IP addresses that are authorized to serve SSH traffic with this certificate. Dangerously, if no principals are specified, this certificate is considered valid for all hosts."
      },
      {
        "name": "public_key",
        "type": "string",
        "required": true,
        "description": "a public key in OpenSSH Authorized Keys format that this certificate signs"
      },
      {
        "name": "ssh_certificate_authority_id",
        "type": "string",
        "required": true,
        "description": "the ssh certificate authority that is used to sign this ssh host certificate"
      },
      {
        "name": "valid_after",
        "type": "string",
        "required": false,
        "description": "The time when the host certificate becomes valid, in RFC 3339 format. Defaults to the current time if unspecified."
      },
      {
        "name": "valid_until",
        "type": "string",
        "required": false,
        "description": "The time when this host certificate becomes invalid, in RFC 3339 format. If unspecified, a default value of one year in the future will be used. The OpenSSH certificates RFC calls this `valid_before`."
      }
    ]
  },
  "delete_ssh_host_certificates": {
    "operation_id": "SshHostCertificatesDelete",
    "display_name": "Delete SSH Host Certificates",
    "category": "SSH Host Certificates",
    "description": "Delete an SSH Host Certificate",
    "method": "DELETE",
    "path": "/ssh_host_certificates/{id}",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "a resource identifier"
      }
    ],
    "body_fields": []
  },
  "get_ssh_host_certificates": {
    "operation_id": "SshHostCertificatesGet",
    "display_name": "Get SSH Host Certificates",
    "category": "SSH Host Certificates",
    "description": "Get detailed information about an SSH Host Certificate",
    "method": "GET",
    "path": "/ssh_host_certificates/{id}",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "a resource identifier"
      }
    ],
    "body_fields": []
  },
  "update_ssh_host_certificates": {
    "operation_id": "SshHostCertificatesUpdate",
    "display_name": "Update SSH Host Certificates",
    "category": "SSH Host Certificates",
    "description": "Update an SSH Host Certificate",
    "method": "PATCH",
    "path": "/ssh_host_certificates/{id}",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": ""
      }
    ],
    "body_fields": [
      {
        "name": "description",
        "type": "string",
        "required": false,
        "description": "human-readable description of this SSH Host Certificate. optional, max 255 bytes."
      },
      {
        "name": "id",
        "type": "string",
        "required": false,
        "description": "n/a"
      },
      {
        "name": "metadata",
        "type": "string",
        "required": false,
        "description": "arbitrary user-defined machine-readable data of this SSH Host Certificate. optional, max 4096 bytes."
      }
    ]
  },
  "list_ssh_user_certificates": {
    "operation_id": "SshUserCertificatesList",
    "display_name": "List SSH User Certificates",
    "category": "SSH User Certificates",
    "description": "List all SSH User Certificates issued on this account",
    "method": "GET",
    "path": "/ssh_user_certificates",
    "params": [
      {
        "name": "before_id",
        "in": "query",
        "type": "string",
        "required": false,
        "description": ""
      },
      {
        "name": "limit",
        "in": "query",
        "type": "string",
        "required": false,
        "description": ""
      }
    ],
    "body_fields": []
  },
  "create_ssh_user_certificates": {
    "operation_id": "SshUserCertificatesCreate",
    "display_name": "Create SSH User Certificates",
    "category": "SSH User Certificates",
    "description": "Create a new SSH User Certificate",
    "method": "POST",
    "path": "/ssh_user_certificates",
    "params": [],
    "body_fields": [
      {
        "name": "critical_options",
        "type": "object",
        "required": false,
        "description": "A map of critical options included in the certificate. Only two critical options are currently defined by OpenSSH: `force-command` and `source-address`. See [the OpenSSH certificate protocol spec](https://github.com/openssh/openssh-portable/blob/master/PROTOCOL.certkeys) for additional details."
      },
      {
        "name": "description",
        "type": "string",
        "required": false,
        "description": "human-readable description of this SSH User Certificate. optional, max 255 bytes."
      },
      {
        "name": "extensions",
        "type": "object",
        "required": false,
        "description": "A map of extensions included in the certificate. Extensions are additional metadata that can be interpreted by the SSH server for any purpose. These can be used to permit or deny the ability to open a terminal, do port forwarding, x11 forwarding, and more. If unspecified, the certificate will include limited permissions with the following extension map: `{\"permit-pty\": \"\", \"permit-user-rc\": \"\"}` OpenSSH understands a number of predefined extensions. See [the OpenSSH certificate protocol spec](https://github.com/openssh/openssh-portable/blob/master/PROTOCOL.certkeys) for additional details."
      },
      {
        "name": "metadata",
        "type": "string",
        "required": false,
        "description": "arbitrary user-defined machine-readable data of this SSH User Certificate. optional, max 4096 bytes."
      },
      {
        "name": "principals",
        "type": "array",
        "required": false,
        "description": "the list of principals included in the ssh user certificate. This is the list of usernames that the certificate holder may sign in as on a machine authorizing the signing certificate authority. Dangerously, if no principals are specified, this certificate may be used to log in as any user."
      },
      {
        "name": "public_key",
        "type": "string",
        "required": true,
        "description": "a public key in OpenSSH Authorized Keys format that this certificate signs"
      },
      {
        "name": "ssh_certificate_authority_id",
        "type": "string",
        "required": true,
        "description": "the ssh certificate authority that is used to sign this ssh user certificate"
      },
      {
        "name": "valid_after",
        "type": "string",
        "required": false,
        "description": "The time when the user certificate becomes valid, in RFC 3339 format. Defaults to the current time if unspecified."
      },
      {
        "name": "valid_until",
        "type": "string",
        "required": false,
        "description": "The time when this host certificate becomes invalid, in RFC 3339 format. If unspecified, a default value of 24 hours will be used. The OpenSSH certificates RFC calls this `valid_before`."
      }
    ]
  },
  "delete_ssh_user_certificates": {
    "operation_id": "SshUserCertificatesDelete",
    "display_name": "Delete SSH User Certificates",
    "category": "SSH User Certificates",
    "description": "Delete an SSH User Certificate",
    "method": "DELETE",
    "path": "/ssh_user_certificates/{id}",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "a resource identifier"
      }
    ],
    "body_fields": []
  },
  "get_ssh_user_certificates": {
    "operation_id": "SshUserCertificatesGet",
    "display_name": "Get SSH User Certificates",
    "category": "SSH User Certificates",
    "description": "Get detailed information about an SSH User Certificate",
    "method": "GET",
    "path": "/ssh_user_certificates/{id}",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "a resource identifier"
      }
    ],
    "body_fields": []
  },
  "update_ssh_user_certificates": {
    "operation_id": "SshUserCertificatesUpdate",
    "display_name": "Update SSH User Certificates",
    "category": "SSH User Certificates",
    "description": "Update an SSH User Certificate",
    "method": "PATCH",
    "path": "/ssh_user_certificates/{id}",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": ""
      }
    ],
    "body_fields": [
      {
        "name": "description",
        "type": "string",
        "required": false,
        "description": "human-readable description of this SSH User Certificate. optional, max 255 bytes."
      },
      {
        "name": "id",
        "type": "string",
        "required": false,
        "description": "n/a"
      },
      {
        "name": "metadata",
        "type": "string",
        "required": false,
        "description": "arbitrary user-defined machine-readable data of this SSH User Certificate. optional, max 4096 bytes."
      }
    ]
  },
  "list_tls_certificates": {
    "operation_id": "TlsCertificatesList",
    "display_name": "List TLS Certificates",
    "category": "TLS Certificates",
    "description": "List all TLS certificates on this account",
    "method": "GET",
    "path": "/tls_certificates",
    "params": [
      {
        "name": "before_id",
        "in": "query",
        "type": "string",
        "required": false,
        "description": "Expects a resource ID as its input. Returns earlier entries in the result set, sorted by ID."
      },
      {
        "name": "limit",
        "in": "query",
        "type": "string",
        "required": false,
        "description": "Constrains the number of results in the dataset. See the [API Overview](https://ngrok.com/docs/api/index#pagination) for details."
      },
      {
        "name": "filter",
        "in": "query",
        "type": "string",
        "required": false,
        "description": "A CEL expression to filter the list results. Supports logical and comparison operators to match on fields such as `id`, `metadata`, `created_at`, and more. See ngrok API Filtering for syntax and field details: https://ngrok.com/docs/api/api-filtering.\nFilterable fields: id, description, metadata, subject_common_name, not_before, not_after, serial_number, created_at"
      }
    ],
    "body_fields": []
  },
  "create_tls_certificates": {
    "operation_id": "TlsCertificatesCreate",
    "display_name": "Create TLS Certificates",
    "category": "TLS Certificates",
    "description": "Upload a new TLS certificate",
    "method": "POST",
    "path": "/tls_certificates",
    "params": [],
    "body_fields": [
      {
        "name": "certificate_pem",
        "type": "string",
        "required": true,
        "description": "chain of PEM-encoded certificates, leaf first. See [Certificate Bundles](https://ngrok.com/docs/cloud-edge/endpoints#certificate-chains)."
      },
      {
        "name": "description",
        "type": "string",
        "required": false,
        "description": "human-readable description of this TLS certificate. optional, max 255 bytes."
      },
      {
        "name": "metadata",
        "type": "string",
        "required": false,
        "description": "arbitrary user-defined machine-readable data of this TLS certificate. optional, max 4096 bytes."
      },
      {
        "name": "private_key_pem",
        "type": "string",
        "required": true,
        "description": "private key for the TLS certificate, PEM-encoded. See [Private Keys](https://ngrok.com/docs/cloud-edge/endpoints#private-keys)."
      }
    ]
  },
  "delete_tls_certificates": {
    "operation_id": "TlsCertificatesDelete",
    "display_name": "Delete TLS Certificates",
    "category": "TLS Certificates",
    "description": "Delete a TLS certificate",
    "method": "DELETE",
    "path": "/tls_certificates/{id}",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "a resource identifier"
      }
    ],
    "body_fields": []
  },
  "get_tls_certificates": {
    "operation_id": "TlsCertificatesGet",
    "display_name": "Get TLS Certificates",
    "category": "TLS Certificates",
    "description": "Get detailed information about a TLS certificate",
    "method": "GET",
    "path": "/tls_certificates/{id}",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "a resource identifier"
      }
    ],
    "body_fields": []
  },
  "update_tls_certificates": {
    "operation_id": "TlsCertificatesUpdate",
    "display_name": "Update TLS Certificates",
    "category": "TLS Certificates",
    "description": "Update attributes of a TLS Certificate by ID",
    "method": "PATCH",
    "path": "/tls_certificates/{id}",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": ""
      }
    ],
    "body_fields": [
      {
        "name": "description",
        "type": "string",
        "required": false,
        "description": "human-readable description of this TLS certificate. optional, max 255 bytes."
      },
      {
        "name": "id",
        "type": "string",
        "required": false,
        "description": "n/a"
      },
      {
        "name": "metadata",
        "type": "string",
        "required": false,
        "description": "arbitrary user-defined machine-readable data of this TLS certificate. optional, max 4096 bytes."
      }
    ]
  },
  "list_tunnel_sessions": {
    "operation_id": "TunnelSessionsList",
    "display_name": "List Tunnel Sessions",
    "category": "Tunnel Sessions",
    "description": "List all online tunnel sessions running on this account.",
    "method": "GET",
    "path": "/tunnel_sessions",
    "params": [
      {
        "name": "before_id",
        "in": "query",
        "type": "string",
        "required": false,
        "description": "Expects a resource ID as its input. Returns earlier entries in the result set, sorted by ID."
      },
      {
        "name": "limit",
        "in": "query",
        "type": "string",
        "required": false,
        "description": "Constrains the number of results in the dataset. See the [API Overview](https://ngrok.com/docs/api/index#pagination) for details."
      },
      {
        "name": "filter",
        "in": "query",
        "type": "string",
        "required": false,
        "description": "A CEL expression to filter the list results. Supports logical and comparison operators to match on fields such as `id`, `metadata`, `created_at`, and more. See ngrok API Filtering for syntax and field details: https://ngrok.com/docs/api/api-filtering.\nFilterable fields: id, metadata, agent_version, ip, os, region, started_at, credential"
      }
    ],
    "body_fields": []
  },
  "get_tunnel_sessions": {
    "operation_id": "TunnelSessionsGet",
    "display_name": "Get Tunnel Sessions",
    "category": "Tunnel Sessions",
    "description": "Get the detailed status of a tunnel session by ID",
    "method": "GET",
    "path": "/tunnel_sessions/{id}",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "a resource identifier"
      }
    ],
    "body_fields": []
  },
  "restart_tunnel_sessions": {
    "operation_id": "TunnelSessionsRestart",
    "display_name": "Restart Tunnel Sessions",
    "category": "Tunnel Sessions",
    "description": "Issues a command instructing the ngrok agent to restart. The agent restarts itself by calling exec() on platforms that support it. This operation is notably not supported on Windows. When an agent restarts, it reconnects with a new tunnel session ID.",
    "method": "POST",
    "path": "/tunnel_sessions/{id}/restart",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "a resource identifier"
      }
    ],
    "body_fields": [
      {
        "name": "id",
        "type": "string",
        "required": false,
        "description": "a resource identifier"
      }
    ]
  },
  "stop_tunnel_sessions": {
    "operation_id": "TunnelSessionsStop",
    "display_name": "Stop Tunnel Sessions",
    "category": "Tunnel Sessions",
    "description": "Issues a command instructing the ngrok agent that started this tunnel session to exit.",
    "method": "POST",
    "path": "/tunnel_sessions/{id}/stop",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "a resource identifier"
      }
    ],
    "body_fields": [
      {
        "name": "id",
        "type": "string",
        "required": false,
        "description": "a resource identifier"
      }
    ]
  },
  "update_tunnel_sessions": {
    "operation_id": "TunnelSessionsUpdate",
    "display_name": "Update Tunnel Sessions",
    "category": "Tunnel Sessions",
    "description": "Issues a command instructing the ngrok agent to update itself to the latest version. After this call completes successfully, the ngrok agent will be in the update process. A caller should wait some amount of time to allow the update to complete (at least 10 seconds) before making a call to the Restart endpoint to request that the agent restart itself to start using the new code. This call will never update an ngrok agent to a new major version which could cause breaking compatibility issues. If you wish to update to a new major version, that must be done manually. Still, please be aware that updating your ngrok agent could break your integration. This call will fail in any of the following circumstances: there is no update available the ngrok agent's configuration disabled update checks the agent is currently in process of updating the agent has already successfully updated but has not yet been restarted",
    "method": "POST",
    "path": "/tunnel_sessions/{id}/update",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": ""
      }
    ],
    "body_fields": [
      {
        "name": "id",
        "type": "string",
        "required": false,
        "description": "n/a"
      }
    ]
  },
  "list_tunnels": {
    "operation_id": "TunnelsList",
    "display_name": "List Tunnels",
    "category": "Tunnels",
    "description": "List all online tunnels currently running on the account.",
    "method": "GET",
    "path": "/tunnels",
    "params": [
      {
        "name": "before_id",
        "in": "query",
        "type": "string",
        "required": false,
        "description": ""
      },
      {
        "name": "limit",
        "in": "query",
        "type": "string",
        "required": false,
        "description": ""
      }
    ],
    "body_fields": []
  },
  "get_tunnels": {
    "operation_id": "TunnelsGet",
    "display_name": "Get Tunnels",
    "category": "Tunnels",
    "description": "Get the status of a tunnel by ID",
    "method": "GET",
    "path": "/tunnels/{id}",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "a resource identifier"
      }
    ],
    "body_fields": []
  },
  "list_secrets": {
    "operation_id": "SecretsList",
    "display_name": "List Secrets",
    "category": "Secrets",
    "description": "List all Secrets owned by account",
    "method": "GET",
    "path": "/vault_secrets",
    "params": [
      {
        "name": "before_id",
        "in": "query",
        "type": "string",
        "required": false,
        "description": "Expects a resource ID as its input. Returns earlier entries in the result set, sorted by ID."
      },
      {
        "name": "limit",
        "in": "query",
        "type": "string",
        "required": false,
        "description": "Constrains the number of results in the dataset. See the [API Overview](https://ngrok.com/docs/api/index#pagination) for details."
      },
      {
        "name": "filter",
        "in": "query",
        "type": "string",
        "required": false,
        "description": "A CEL expression to filter the list results. Supports logical and comparison operators to match on fields such as `id`, `metadata`, `created_at`, and more. See ngrok API Filtering for syntax and field details: https://ngrok.com/docs/api/api-filtering.\nFilterable fields: id, created_at, description, metadata, name"
      }
    ],
    "body_fields": []
  },
  "create_secrets": {
    "operation_id": "SecretsCreate",
    "display_name": "Create Secrets",
    "category": "Secrets",
    "description": "Create a new Secret",
    "method": "POST",
    "path": "/vault_secrets",
    "params": [],
    "body_fields": [
      {
        "name": "description",
        "type": "string",
        "required": false,
        "description": "description of Secret"
      },
      {
        "name": "metadata",
        "type": "string",
        "required": false,
        "description": "Arbitrary user-defined metadata for this Secret"
      },
      {
        "name": "name",
        "type": "string",
        "required": false,
        "description": "Name of secret"
      },
      {
        "name": "value",
        "type": "string",
        "required": false,
        "description": "Value of secret"
      },
      {
        "name": "vault_id",
        "type": "string",
        "required": false,
        "description": "unique identifier of the referenced vault"
      },
      {
        "name": "vault_name",
        "type": "string",
        "required": false,
        "description": "name of the referenced vault"
      }
    ]
  },
  "delete_secrets": {
    "operation_id": "SecretsDelete",
    "display_name": "Delete Secrets",
    "category": "Secrets",
    "description": "Delete a Secret",
    "method": "DELETE",
    "path": "/vault_secrets/{id}",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "a resource identifier"
      }
    ],
    "body_fields": []
  },
  "get_secrets": {
    "operation_id": "SecretsGet",
    "display_name": "Get Secrets",
    "category": "Secrets",
    "description": "Get a Secret by ID",
    "method": "GET",
    "path": "/vault_secrets/{id}",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "a resource identifier"
      }
    ],
    "body_fields": []
  },
  "update_secrets": {
    "operation_id": "SecretsUpdate",
    "display_name": "Update Secrets",
    "category": "Secrets",
    "description": "Update an existing Secret by ID",
    "method": "PATCH",
    "path": "/vault_secrets/{id}",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "identifier for Secret"
      }
    ],
    "body_fields": [
      {
        "name": "description",
        "type": "string",
        "required": false,
        "description": "description of Secret"
      },
      {
        "name": "id",
        "type": "string",
        "required": false,
        "description": "identifier for Secret"
      },
      {
        "name": "metadata",
        "type": "string",
        "required": false,
        "description": "Arbitrary user-defined metadata for this Secret"
      },
      {
        "name": "name",
        "type": "string",
        "required": false,
        "description": "Name of secret"
      },
      {
        "name": "value",
        "type": "string",
        "required": false,
        "description": "Value of secret"
      }
    ]
  },
  "list_vaults": {
    "operation_id": "VaultsList",
    "display_name": "List Vaults",
    "category": "Vaults",
    "description": "List all Vaults owned by account",
    "method": "GET",
    "path": "/vaults",
    "params": [
      {
        "name": "before_id",
        "in": "query",
        "type": "string",
        "required": false,
        "description": "Expects a resource ID as its input. Returns earlier entries in the result set, sorted by ID."
      },
      {
        "name": "limit",
        "in": "query",
        "type": "string",
        "required": false,
        "description": "Constrains the number of results in the dataset. See the [API Overview](https://ngrok.com/docs/api/index#pagination) for details."
      },
      {
        "name": "filter",
        "in": "query",
        "type": "string",
        "required": false,
        "description": "A CEL expression to filter the list results. Supports logical and comparison operators to match on fields such as `id`, `metadata`, `created_at`, and more. See ngrok API Filtering for syntax and field details: https://ngrok.com/docs/api/api-filtering.\nFilterable fields: id, created_at, description, metadata, name"
      }
    ],
    "body_fields": []
  },
  "create_vaults": {
    "operation_id": "VaultsCreate",
    "display_name": "Create Vaults",
    "category": "Vaults",
    "description": "Create a new Vault",
    "method": "POST",
    "path": "/vaults",
    "params": [],
    "body_fields": [
      {
        "name": "description",
        "type": "string",
        "required": false,
        "description": "description of Vault"
      },
      {
        "name": "metadata",
        "type": "string",
        "required": false,
        "description": "Arbitrary user-defined metadata for this Vault"
      },
      {
        "name": "name",
        "type": "string",
        "required": false,
        "description": "Name of vault"
      }
    ]
  },
  "delete_vaults": {
    "operation_id": "VaultsDelete",
    "display_name": "Delete Vaults",
    "category": "Vaults",
    "description": "Delete a Vault",
    "method": "DELETE",
    "path": "/vaults/{id}",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "a resource identifier"
      }
    ],
    "body_fields": []
  },
  "get_vaults": {
    "operation_id": "VaultsGet",
    "display_name": "Get Vaults",
    "category": "Vaults",
    "description": "Get a Vault by ID",
    "method": "GET",
    "path": "/vaults/{id}",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "a resource identifier"
      }
    ],
    "body_fields": []
  },
  "update_vaults": {
    "operation_id": "VaultsUpdate",
    "display_name": "Update Vaults",
    "category": "Vaults",
    "description": "Update an existing Vault by ID",
    "method": "PATCH",
    "path": "/vaults/{id}",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "identifier for Vault"
      }
    ],
    "body_fields": [
      {
        "name": "description",
        "type": "string",
        "required": false,
        "description": "description of Vault"
      },
      {
        "name": "id",
        "type": "string",
        "required": false,
        "description": "identifier for Vault"
      },
      {
        "name": "metadata",
        "type": "string",
        "required": false,
        "description": "Arbitrary user-defined metadata for this Vault"
      },
      {
        "name": "name",
        "type": "string",
        "required": false,
        "description": "Name of vault"
      }
    ]
  },
  "vaults_get_secrets_by_vault": {
    "operation_id": "VaultsGetSecretsByVault",
    "display_name": "Vaults Get Secrets By Vault",
    "category": "Vaults",
    "description": "Get Secrets by Vault ID",
    "method": "GET",
    "path": "/vaults/{id}/secrets",
    "params": [
      {
        "name": "id",
        "in": "path",
        "type": "string",
        "required": true,
        "description": "a resource identifier"
      },
      {
        "name": "before_id",
        "in": "query",
        "type": "string",
        "required": false,
        "description": ""
      },
      {
        "name": "limit",
        "in": "query",
        "type": "string",
        "required": false,
        "description": ""
      }
    ],
    "body_fields": []
  }
}
''')


class NgrokAPIKeyCredential(BaseModel):
    """API key created in the ngrok dashboard, distinct from an agent authtoken."""

    credential_type: Literal["ngrok_api_key"] = Field(
        "ngrok_api_key", json_schema_extra={"ui:hidden": True}
    )
    api_key: str = Field(
        ..., title="API Key", description="ngrok API key (not your agent authtoken)",
        json_schema_extra={"ui:widget": "password"},
    )

    model_config = ConfigDict(title="ngrok API Key", json_schema_extra={
        "x-credential-url": "https://dashboard.ngrok.com/api-keys",
        "x-credential-instructions": "Create an API key in the ngrok dashboard. Agent authtokens cannot authenticate the REST API.",
    })


_TYPES: Dict[str, Any] = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "object": Dict[str, Any],
    "array": List[Any],
    "any": Any,
}


def _title(name: str) -> str:
    return re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", name.replace("_", " ")).title()


def _operation_model(operation: str, spec: Dict[str, Any]) -> type[BaseModel]:
    fields: Dict[str, Any] = {
        "operation": (
            Literal[operation],
            Field(operation, title=spec["display_name"],
                  description=spec["description"] or None, json_schema_extra={
                "const": operation,
                "ui:hidden": True,
                "x-category": spec["category"],
                "x-display-name": spec["display_name"],
                "x-is-trigger": False,
            }),
        ),
    }
    for param in spec["params"]:
        kind = _TYPES.get(param["type"], Any)
        required = param["required"]
        fields[param["name"]] = (
            kind if required else Optional[kind],
            Field(... if required else None,
                  title=_title(param["name"]),
                  description=param["description"] or None,
                  ge=param.get("minimum"), le=param.get("maximum")),
        )
    for prop in spec["body_fields"]:
        key = f"body_{prop['name']}"
        kind = _TYPES.get(prop["type"], Any)
        if prop["name"] in {"sources", "resolves_to"} and prop["type"] == "array":
            kind = List[Dict[str, Any]]
        required = prop["required"]
        sensitive = (bool(re.search(r"secret|token|password|private_key|api_key", prop["name"], re.I))
                     or (spec["category"] in {"Secrets", "AI Gateway Provider Keys"} and prop["name"] == "value"))
        extra: Dict[str, Any] = {}
        if sensitive and prop["type"] == "string":
            extra["ui:widget"] = "password"
        if "enum" in prop:
            extra["enum"] = prop["enum"]
            extra["x-enum-searchable"] = True
        fields[key] = (
            kind if required else Optional[kind],
            Field(... if required else None,
                  title=_title(prop["name"]),
                  description=prop["description"] or None,
                  json_schema_extra=extra or None, max_length=prop.get("maxLength")),
        )
    if spec["body_fields"] and spec.get("additional_properties", True):
        fields["extra_body"] = (
            Optional[Dict[str, Any]],
            Field(None, title="Additional Body Fields",
                  description="Optional JSON fields merged into the request body"),
        )
    return create_model(
        f"Ngrok{spec['operation_id']}Config", __module__=__name__,
        __config__=ConfigDict(extra="forbid") if spec.get("ai_gateway") else ConfigDict(),
        **fields
    )


_OPERATION_MODELS = [_operation_model(key, spec) for key, spec in OPERATIONS.items()]
for _model in _OPERATION_MODELS:
    globals()[_model.__name__] = _model
# EventTarget supports log/stream sinks, not HTTP callbacks. These creation-time
# filterable resources use scheduled polling instead.
POLL_TRIGGERS = {
    "on_new_endpoint": ("/endpoints", "endpoints", "New Endpoint"),
    "on_new_tunnel_session": ("/tunnel_sessions", "tunnel_sessions", "New Tunnel Session"),
    "on_new_reserved_domain": ("/reserved_domains", "reserved_domains", "New Reserved Domain"),
}


def _poll_model(operation: str, title: str) -> type[BaseModel]:
    return create_model(
        "Ngrok" + "".join(part.title() for part in operation.split("_")) + "Config",
        __module__=__name__, __base__=PollTriggerConfigBase,
        operation=(Literal[operation], Field(operation, title=title, json_schema_extra={
            "const": operation, "ui:hidden": True, "x-category": "Triggers",
            "x-is-trigger": True, "x-display-name": title,
        })),
        filter=(Optional[str], Field(None, title="Filter", description=(
            "Optional ngrok CEL expression evaluated against obj, including created_at "
            "(started_at for tunnel sessions). Changing the filter establishes a new baseline. "
            "See https://ngrok.com/docs/api/api-filtering."
        ))),
    )


_POLL_MODELS = [_poll_model(operation, spec[2]) for operation, spec in POLL_TRIGGERS.items()]
for _model in _POLL_MODELS:
    globals()[_model.__name__] = _model
NgrokConfig = Annotated[Union[tuple(_OPERATION_MODELS + _POLL_MODELS)], Discriminator("operation")]


class NgrokNodeConfig(NodeConfig[NgrokConfig, NgrokAPIKeyCredential]):
    """One ngrok operation and its API key."""


async def _ngrok_request(
    api_key: str,
    method: str,
    path: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    body: Optional[Dict[str, Any]] = None,
    ai_gateway: bool = False,
) -> Dict[str, Any]:
    """Perform one fixed-host API call without logging a key or request body."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }
    if not ai_gateway:
        headers["ngrok-version"] = API_VERSION
    api_base = AI_GATEWAY_API_BASE if ai_gateway else API_BASE
    if body is not None:
        headers["Content-Type"] = "application/json"
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.request(
                method, f"{api_base}{path}", headers=headers, params=params, json=body,
            )
    except httpx.TimeoutException:
        return {"status": "error", "error": "ngrok API request timed out", "status_code": 408}
    except httpx.HTTPError as exc:
        logger.warning("ngrok API transport error: %s", type(exc).__name__)
        return {"status": "error", "error": "Could not reach the ngrok API", "status_code": 502}

    if not response.content:
        data: Any = {"success": True}
    else:
        try:
            data = response.json()
        except ValueError:
            data = {"raw": response.text[:2000]}
    if response.status_code >= 400:
        if isinstance(data, dict):
            message = data.get("msg") or data.get("message") or data.get("error")
            code = data.get("error_code") or data.get("errorCode")
        else:
            message, code = str(data), None
        return {
            "status": "error", "error": str(message or "ngrok API request failed")[:1000],
            "error_code": code, "status_code": response.status_code,
        }
    return {"status": "success", "data": data, "status_code": response.status_code}


class NgrokNode(ScheduledPollTriggerMixin, WorkflowNode):
    """Provision and inspect ngrok endpoints, domains, tunnels and account resources."""

    integration_type = "automation-ngrok"

    connection_evidence = ConnectionEvidence(
        operation="list_endpoints",
        identity_operation="list_api_keys",
        noun="endpoints",
        label_keys=("url", "name", "description", "id"),
        identity_keys=("description", "id", "name"),
    )

    edit_examples = [
        "List the active ngrok endpoints in my account",
        "Create a cloud endpoint for my webhook test app",
        "Show my reserved domains and their certificate status",
        "List my ngrok vaults and API keys",
    ]

    @classmethod
    def get_config_model(cls):
        return NgrokNodeConfig

    @classmethod
    def should_propagate_output(cls, output: Dict[str, Any], config: Dict[str, Any]) -> bool:
        if config.get("operation") in POLL_TRIGGERS:
            return bool(output.get("new_item_count"))
        return super().should_propagate_output(output, config)

    @classmethod
    def resolve_agent_event(cls, output: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        operation = output.get("operation")
        if operation not in POLL_TRIGGERS:
            return super().resolve_agent_event(output)
        _, key, title = POLL_TRIGGERS[operation]
        items = output.get(key, [])
        if not items:
            return None
        lines = []
        for item in items[:10]:
            if operation == "on_new_endpoint":
                principal = item.get("principal") or {}
                detail = (f"{item.get('url', '')} — {item.get('name', '')} "
                          f"{item.get('description', '')}; type {item.get('type', '')}; "
                          f"owner {principal.get('id', '')}; created {item.get('created_at', '')}")
            elif operation == "on_new_tunnel_session":
                credential = item.get("credential") or {}
                detail = (f"agent {item.get('agent_version', '')} on {item.get('os', '')} "
                          f"from {item.get('ip', '')}; credential {credential.get('id', '')}; "
                          f"started {item.get('started_at', '')}")
            else:
                detail = (f"{item.get('domain', '')} — {item.get('description', '')}; "
                          f"created {item.get('created_at', '')}")
            lines.append(f"- {detail[:800]}; region {item.get('region', '')}; id {item['id']}")
        if len(items) > 10:
            lines.append(f"- … and {len(items) - 10} more")
        return {"text": f"ngrok: {len(items)} {title.lower()}(s):\n" + "\n".join(lines),
                "title": f"ngrok: {title.lower()}", "conversation_key": None}

    async def _poll_new_resources(self, config: PollTriggerConfigBase) -> Dict[str, Any]:
        path, key, _ = POLL_TRIGGERS[config.operation]
        params: Dict[str, Any] = {"limit": "100"}
        if config.filter:
            params["filter"] = config.filter
        items: List[Dict[str, Any]] = []
        cursors: set[str] = set()
        for _ in range(100):
            result = await _ngrok_request(self.config.credentials.api_key, "GET", path, params=params)
            if result["status"] != "success":
                return {"operation": config.operation, **result}
            data = result["data"]
            if not isinstance(data, dict) or not isinstance(data.get(key), list):
                raise ValueError(f"ngrok response did not contain {key}")
            page = data[key]
            if any(not isinstance(item, dict) or not item.get("id") for item in page):
                raise ValueError("ngrok list item has no resource id")
            items.extend(page)
            next_uri = data.get("next_page_uri")
            if not next_uri:
                break
            next_page = urlsplit(next_uri)
            cursor = parse_qs(next_page.query).get("before_id", [None])[0]
            if (next_page.scheme != "https" or next_page.netloc != "api.ngrok.com"
                    or next_page.path != path or not cursor or cursor in cursors):
                raise ValueError("ngrok returned an invalid or repeated pagination cursor")
            cursors.add(cursor)
            params["before_id"] = cursor
        else:
            raise ValueError("ngrok poll exceeded 10,000 resources; narrow the filter")
        fresh = await self._filter_unseen(items, lambda item: str(item["id"]))
        return {"operation": config.operation, "status": "success", key: fresh,
                "new_item_count": len(fresh)}

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        del inputs
        if not isinstance(self.config, NgrokNodeConfig):
            raise ValueError("Valid ngrok configuration is required")
        if not self.config.credentials or not self.config.credentials.api_key:
            raise ValueError("A ngrok API key credential is required")
        config = self.config.config
        operation = config.operation
        if operation in POLL_TRIGGERS:
            return await self._poll_new_resources(config)
        spec = OPERATIONS[operation]
        values = config.model_dump()
        path = spec["path"]
        params: Dict[str, Any] = {}
        for param in spec["params"]:
            name = param["name"]
            value = values.get(name)
            if value is None or value == "":
                continue
            if param["in"] == "path":
                path = path.replace("{" + name + "}", quote(str(value), safe=""))
            else:
                params[name] = value
        body: Optional[Dict[str, Any]] = None
        if spec["body_fields"]:
            body = {
                prop["name"]: values[f"body_{prop['name']}"]
                for prop in spec["body_fields"]
                if (values.get(f"body_{prop['name']}") is not None
                    or (prop.get("nullable") and f"body_{prop['name']}" in config.model_fields_set))
            }
            body.update(values.get("extra_body") or {})
        result = await _ngrok_request(
            self.config.credentials.api_key, spec["method"], path,
            params=params or None, body=body, ai_gateway=spec.get("ai_gateway", False),
        )
        return {"operation": operation, **result}
