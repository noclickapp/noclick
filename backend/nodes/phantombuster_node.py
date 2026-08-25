"""
PhantomBuster automation node.

Provides workflow integration with PhantomBuster (v2 REST API) for operations including:
- Account: get current user/account, update account
- Agents (Phantoms): list, get, get output, list deleted, launch, launch-soon,
  launch-sync, stop, save, delete, unschedule-all
- Containers (runs): list, get, get output, get result object (scraped data), attach
- Scripts: list, get, get code, save, delete, set visibility, set access list
- Branches: list, diff, create, delete, release
- Organization: get org, resources, running containers, agent groups (get/save),
  export agent/container usage, CRM access/resources, save CRM contact
- Org storage: save/save-many/delete leads, leads by list; list/get/save/delete lead lists
- Identities: save, save-with-token, generate token, search, save event
- Strategic: list ICPs, list buyer personas
- AI / utilities: AI completion, advice, task; solve hCaptcha/reCAPTCHA; SERP; IP geolocation
- Webhook Trigger: receive per-Phantom completion notifications

Authentication: API Key. The workspace key is sent in the X-Phantombuster-Key-1
header (the long-standing form PhantomBuster still accepts; X-Phantombuster-Key
is the newer alias). No OAuth.
API Base URL: https://api.phantombuster.com/api/v2
Documentation: https://hub.phantombuster.com/reference

PhantomBuster has no OAuth: all access uses a static workspace API key passed in
the non-standard `X-Phantombuster-Key-1` header (no Bearer prefix). v2 endpoints
return plain JSON. Webhooks are configured per-Phantom in the agent's dashboard
settings (no registerable webhook API), so the trigger is a passive receiver.
"""

import logging
import time
from typing import Dict, Any, Optional, Literal, Union, Annotated
from uuid import UUID
from pydantic import BaseModel, Field, ConfigDict, Discriminator
import httpx

from nodes.core.base import WorkflowNode, NodeConfig

logger = logging.getLogger(__name__)

PHANTOMBUSTER_API_BASE = "https://api.phantombuster.com/api/v2"


def _dropdown(field_name: str, placeholder: str, custom_placeholder: str) -> Dict[str, Any]:
    """Build an ``x-dynamic-options`` spec for a listable-resource dropdown."""
    return {
        "x-dynamic-options": {
            "field_name": field_name,
            "placeholder": placeholder,
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": custom_placeholder,
        }
    }


_SCRIPT_DROPDOWN = _dropdown("script_id", "Select a script...", "Or paste script ID")
_LIST_DROPDOWN = _dropdown("list_id", "Select a lead list...", "Or paste list ID")


# ============================================================================
# Credential Schema
# ============================================================================


class PhantomBusterApiKeyCredential(BaseModel):
    """API Key credential for PhantomBuster."""

    credential_type: Literal["phantombuster_api_key"] = Field(
        "phantombuster_api_key", json_schema_extra={"ui:hidden": True}
    )
    api_key: str = Field(
        ...,
        title="API Key",
        description="Your PhantomBuster workspace API key. Reveal it in Settings under the API key section.",
        json_schema_extra={"ui:widget": "password"},
    )

    model_config = ConfigDict(
        json_schema_extra={"x-credential-url": "https://phantombuster.com/settings"}
    )


PhantomBusterCredential = PhantomBusterApiKeyCredential


# ============================================================================
# Account Operations
# ============================================================================


class PhantomBusterGetUserConfig(BaseModel):
    """Fetch the current account info, plan/quota, and running agents."""

    operation: Literal["get_user"] = Field(
        "get_user",
        json_schema_extra={
            "const": "get_user",
            "ui:hidden": True,
            "x-category": "Account",
            "x-is-trigger": False,
            "x-display-name": "Get Account",
        },
        title="Get Account",
    )


# ============================================================================
# Agent (Phantom) Operations
# ============================================================================


class PhantomBusterListAgentsConfig(BaseModel):
    """List every agent (Phantom) in the workspace."""

    operation: Literal["list_agents"] = Field(
        "list_agents",
        json_schema_extra={
            "const": "list_agents",
            "ui:hidden": True,
            "x-category": "Agents",
            "x-is-trigger": False,
            "x-display-name": "List Agents",
        },
        title="List Agents",
    )


class PhantomBusterGetAgentConfig(BaseModel):
    """Fetch a single agent's details and configuration."""

    operation: Literal["get_agent"] = Field(
        "get_agent",
        json_schema_extra={
            "const": "get_agent",
            "ui:hidden": True,
            "x-category": "Agents",
            "x-is-trigger": False,
            "x-display-name": "Get Agent",
        },
        title="Get Agent",
    )
    agent_id: str = Field(
        ...,
        title="Agent",
        description="The ID of the agent (Phantom) to fetch",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "agent_id",
                "placeholder": "Select an agent...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste agent ID",
            }
        },
    )


class PhantomBusterLaunchAgentConfig(BaseModel):
    """Start an agent run; returns a container ID."""

    operation: Literal["launch_agent"] = Field(
        "launch_agent",
        json_schema_extra={
            "const": "launch_agent",
            "ui:hidden": True,
            "x-category": "Agents",
            "x-is-trigger": False,
            "x-display-name": "Launch Agent",
        },
        title="Launch Agent",
    )
    agent_id: str = Field(
        ...,
        title="Agent",
        description="The ID of the agent (Phantom) to launch",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "agent_id",
                "placeholder": "Select an agent...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste agent ID",
            }
        },
    )
    argument: Optional[str] = Field(
        None,
        title="Argument (JSON)",
        description="Optional JSON object of argument overrides passed to the Phantom",
        json_schema_extra={"ui:widget": "textarea"},
    )


class PhantomBusterLaunchAgentSoonConfig(BaseModel):
    """Queue the agent to launch as soon as a slot is free."""

    operation: Literal["launch_agent_soon"] = Field(
        "launch_agent_soon",
        json_schema_extra={
            "const": "launch_agent_soon",
            "ui:hidden": True,
            "x-category": "Agents",
            "x-is-trigger": False,
            "x-display-name": "Launch Agent (Queued)",
        },
        title="Launch Agent (Queued)",
    )
    agent_id: str = Field(
        ...,
        title="Agent",
        description="The ID of the agent (Phantom) to queue",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "agent_id",
                "placeholder": "Select an agent...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste agent ID",
            }
        },
    )
    minutes: str = Field(
        "0",
        title="Delay (minutes)",
        description="Launch within this many minutes (0 = as soon as a slot is free). A manual launch before then cancels it.",
    )
    argument: Optional[str] = Field(
        None,
        title="Argument (JSON)",
        description="Optional JSON object of argument overrides passed to the Phantom",
        json_schema_extra={"ui:widget": "textarea"},
    )


class PhantomBusterLaunchAgentSyncConfig(BaseModel):
    """Launch and block until completion, returning the result inline."""

    operation: Literal["launch_agent_sync"] = Field(
        "launch_agent_sync",
        json_schema_extra={
            "const": "launch_agent_sync",
            "ui:hidden": True,
            "x-category": "Agents",
            "x-is-trigger": False,
            "x-display-name": "Launch Agent (Sync)",
        },
        title="Launch Agent (Sync)",
    )
    agent_id: str = Field(
        ...,
        title="Agent",
        description="The ID of the agent (Phantom) to launch synchronously",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "agent_id",
                "placeholder": "Select an agent...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste agent ID",
            }
        },
    )
    argument: Optional[str] = Field(
        None,
        title="Argument (JSON)",
        description="Optional JSON object of argument overrides passed to the Phantom",
        json_schema_extra={"ui:widget": "textarea"},
    )


class PhantomBusterStopAgentConfig(BaseModel):
    """Abort a running agent / its container."""

    operation: Literal["stop_agent"] = Field(
        "stop_agent",
        json_schema_extra={
            "const": "stop_agent",
            "ui:hidden": True,
            "x-category": "Agents",
            "x-is-trigger": False,
            "x-display-name": "Stop Agent",
        },
        title="Stop Agent",
    )
    agent_id: str = Field(
        ...,
        title="Agent",
        description="The ID of the running agent to stop",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "agent_id",
                "placeholder": "Select an agent...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste agent ID",
            }
        },
    )


class PhantomBusterSaveAgentConfig(BaseModel):
    """Create or update an agent's configuration/arguments."""

    operation: Literal["save_agent"] = Field(
        "save_agent",
        json_schema_extra={
            "const": "save_agent",
            "ui:hidden": True,
            "x-category": "Agents",
            "x-is-trigger": False,
            "x-display-name": "Save Agent",
        },
        title="Save Agent",
    )
    agent_payload: str = Field(
        ...,
        title="Agent Payload (JSON)",
        description="JSON object describing the agent to create or update (include id to update)",
        json_schema_extra={"ui:widget": "textarea"},
    )


class PhantomBusterDeleteAgentConfig(BaseModel):
    """Permanently remove an agent."""

    operation: Literal["delete_agent"] = Field(
        "delete_agent",
        json_schema_extra={
            "const": "delete_agent",
            "ui:hidden": True,
            "x-category": "Agents",
            "x-is-trigger": False,
            "x-display-name": "Delete Agent",
        },
        title="Delete Agent",
    )
    agent_id: str = Field(
        ...,
        title="Agent",
        description="The ID of the agent to delete",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "agent_id",
                "placeholder": "Select an agent...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste agent ID",
            }
        },
    )


# ============================================================================
# Container (run) Operations
# ============================================================================


class PhantomBusterListContainersConfig(BaseModel):
    """List execution containers (run history) for an agent."""

    operation: Literal["list_containers"] = Field(
        "list_containers",
        json_schema_extra={
            "const": "list_containers",
            "ui:hidden": True,
            "x-category": "Containers",
            "x-is-trigger": False,
            "x-display-name": "List Containers",
        },
        title="List Containers",
    )
    agent_id: str = Field(
        ...,
        title="Agent",
        description="The ID of the agent whose run history to list",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "agent_id",
                "placeholder": "Select an agent...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste agent ID",
            }
        },
    )


class PhantomBusterGetContainerConfig(BaseModel):
    """Fetch a single container's status/metadata for one run."""

    operation: Literal["get_container"] = Field(
        "get_container",
        json_schema_extra={
            "const": "get_container",
            "ui:hidden": True,
            "x-category": "Containers",
            "x-is-trigger": False,
            "x-display-name": "Get Container",
        },
        title="Get Container",
    )
    container_id: str = Field(
        ..., title="Container ID", description="The ID of the container (run) to fetch"
    )


class PhantomBusterGetContainerOutputConfig(BaseModel):
    """Retrieve console output / progress / result-object URL for a run."""

    operation: Literal["get_container_output"] = Field(
        "get_container_output",
        json_schema_extra={
            "const": "get_container_output",
            "ui:hidden": True,
            "x-category": "Containers",
            "x-is-trigger": False,
            "x-display-name": "Get Container Output",
        },
        title="Get Container Output",
    )
    container_id: str = Field(
        ..., title="Container ID", description="The ID of the container (run) whose output to retrieve"
    )


# ============================================================================
# Script Operations
# ============================================================================


class PhantomBusterListScriptsConfig(BaseModel):
    """List all scripts (Phantom definitions) in the workspace."""

    operation: Literal["list_scripts"] = Field(
        "list_scripts",
        json_schema_extra={
            "const": "list_scripts",
            "ui:hidden": True,
            "x-category": "Scripts",
            "x-is-trigger": False,
            "x-display-name": "List Scripts",
        },
        title="List Scripts",
    )


class PhantomBusterGetScriptConfig(BaseModel):
    """Fetch metadata for a single script."""

    operation: Literal["get_script"] = Field(
        "get_script",
        json_schema_extra={
            "const": "get_script",
            "ui:hidden": True,
            "x-category": "Scripts",
            "x-is-trigger": False,
            "x-display-name": "Get Script",
        },
        title="Get Script",
    )
    script_id: str = Field(
        ..., title="Script ID", description="The ID of the script to fetch",
        json_schema_extra=_SCRIPT_DROPDOWN,
    )


class PhantomBusterGetScriptCodeConfig(BaseModel):
    """Retrieve the raw code of a script."""

    operation: Literal["get_script_code"] = Field(
        "get_script_code",
        json_schema_extra={
            "const": "get_script_code",
            "ui:hidden": True,
            "x-category": "Scripts",
            "x-is-trigger": False,
            "x-display-name": "Get Script Code",
        },
        title="Get Script Code",
    )
    script_id: str = Field(
        ..., title="Script ID", description="The ID of the script whose code to retrieve",
        json_schema_extra=_SCRIPT_DROPDOWN,
    )


class PhantomBusterSaveScriptConfig(BaseModel):
    """Create or update a script's code/metadata."""

    operation: Literal["save_script"] = Field(
        "save_script",
        json_schema_extra={
            "const": "save_script",
            "ui:hidden": True,
            "x-category": "Scripts",
            "x-is-trigger": False,
            "x-display-name": "Save Script",
        },
        title="Save Script",
    )
    script_payload: str = Field(
        ...,
        title="Script Payload (JSON)",
        description="JSON object describing the script to create or update (include id to update)",
        json_schema_extra={"ui:widget": "textarea"},
    )


class PhantomBusterDeleteScriptConfig(BaseModel):
    """Remove a script."""

    operation: Literal["delete_script"] = Field(
        "delete_script",
        json_schema_extra={
            "const": "delete_script",
            "ui:hidden": True,
            "x-category": "Scripts",
            "x-is-trigger": False,
            "x-display-name": "Delete Script",
        },
        title="Delete Script",
    )
    script_id: str = Field(
        ..., title="Script ID", description="The ID of the script to delete",
        json_schema_extra=_SCRIPT_DROPDOWN,
    )


# ============================================================================
# Organization Operations
# ============================================================================


class PhantomBusterGetOrgConfig(BaseModel):
    """Fetch organization/workspace details."""

    operation: Literal["get_org"] = Field(
        "get_org",
        json_schema_extra={
            "const": "get_org",
            "ui:hidden": True,
            "x-category": "Organization",
            "x-is-trigger": False,
            "x-display-name": "Get Organization",
        },
        title="Get Organization",
    )


class PhantomBusterGetOrgResourcesConfig(BaseModel):
    """Fetch resource/quota allocation for the org."""

    operation: Literal["get_org_resources"] = Field(
        "get_org_resources",
        json_schema_extra={
            "const": "get_org_resources",
            "ui:hidden": True,
            "x-category": "Organization",
            "x-is-trigger": False,
            "x-display-name": "Get Org Resources",
        },
        title="Get Org Resources",
    )


# ============================================================================
# Org Storage Operations
# ============================================================================


class PhantomBusterSaveLeadsConfig(BaseModel):
    """Store / upsert lead records into workspace storage."""

    operation: Literal["save_leads"] = Field(
        "save_leads",
        json_schema_extra={
            "const": "save_leads",
            "ui:hidden": True,
            "x-category": "Org Storage",
            "x-is-trigger": False,
            "x-display-name": "Save Leads",
        },
        title="Save Leads",
    )
    leads_payload: str = Field(
        ...,
        title="Leads Payload (JSON)",
        description="JSON object/array of lead records to store or upsert",
        json_schema_extra={"ui:widget": "textarea"},
    )


class PhantomBusterListLeadListsConfig(BaseModel):
    """List all saved lead lists in the workspace."""

    operation: Literal["list_lead_lists"] = Field(
        "list_lead_lists",
        json_schema_extra={
            "const": "list_lead_lists",
            "ui:hidden": True,
            "x-category": "Org Storage",
            "x-is-trigger": False,
            "x-display-name": "List Lead Lists",
        },
        title="List Lead Lists",
    )


class PhantomBusterSaveLeadListConfig(BaseModel):
    """Create or update a lead list."""

    operation: Literal["save_lead_list"] = Field(
        "save_lead_list",
        json_schema_extra={
            "const": "save_lead_list",
            "ui:hidden": True,
            "x-category": "Org Storage",
            "x-is-trigger": False,
            "x-display-name": "Save Lead List",
        },
        title="Save Lead List",
    )
    list_payload: str = Field(
        ...,
        title="List Payload (JSON)",
        description="JSON object describing the lead list to create or update",
        json_schema_extra={"ui:widget": "textarea"},
    )


# ============================================================================
# AI / Utility Operations
# ============================================================================


class PhantomBusterAiCompletionConfig(BaseModel):
    """Generate an AI text completion (PhantomBuster-hosted AI)."""

    operation: Literal["ai_completion"] = Field(
        "ai_completion",
        json_schema_extra={
            "const": "ai_completion",
            "ui:hidden": True,
            "x-category": "AI & Utilities",
            "x-is-trigger": False,
            "x-display-name": "AI Completion",
        },
        title="AI Completion",
    )
    prompt: str = Field(
        ...,
        title="Prompt",
        description="The prompt to generate a completion for",
        json_schema_extra={"ui:widget": "textarea"},
    )


class PhantomBusterSolveHcaptchaConfig(BaseModel):
    """Submit an hCaptcha challenge for solving."""

    operation: Literal["solve_hcaptcha"] = Field(
        "solve_hcaptcha",
        json_schema_extra={
            "const": "solve_hcaptcha",
            "ui:hidden": True,
            "x-category": "AI & Utilities",
            "x-is-trigger": False,
            "x-display-name": "Solve hCaptcha",
        },
        title="Solve hCaptcha",
    )
    site_key: str = Field(
        ..., title="Site Key", description="The hCaptcha site key for the challenge"
    )
    page_url: str = Field(
        ..., title="Page URL", description="The URL of the page presenting the hCaptcha"
    )


class PhantomBusterIpLocationConfig(BaseModel):
    """Resolve geographic location from an IP address."""

    operation: Literal["ip_location"] = Field(
        "ip_location",
        json_schema_extra={
            "const": "ip_location",
            "ui:hidden": True,
            "x-category": "AI & Utilities",
            "x-is-trigger": False,
            "x-display-name": "IP Geolocation",
        },
        title="IP Geolocation",
    )
    ip: str = Field(
        ..., title="IP Address", description="The IP address to geolocate"
    )


_AGENT_DROPDOWN = {
    "x-dynamic-options": {
        "field_name": "agent_id",
        "placeholder": "Select an agent...",
        "searchable": True,
        "allow_custom": True,
        "custom_placeholder": "Or paste agent ID",
    }
}


class PhantomBusterGetAgentOutputConfig(BaseModel):
    """Fetch the incremental console output of an agent's most-recent run."""

    operation: Literal["get_agent_output"] = Field(
        "get_agent_output",
        json_schema_extra={
            "const": "get_agent_output", "ui:hidden": True, "x-category": "Agents",
            "x-is-trigger": False, "x-display-name": "Get Agent Output",
        },
        title="Get Agent Output",
    )
    agent_id: str = Field(
        ..., title="Agent", description="The agent whose latest run output to fetch",
        json_schema_extra=_AGENT_DROPDOWN,
    )


class PhantomBusterListDeletedAgentsConfig(BaseModel):
    """List soft-deleted agents in the workspace."""

    operation: Literal["list_deleted_agents"] = Field(
        "list_deleted_agents",
        json_schema_extra={
            "const": "list_deleted_agents", "ui:hidden": True, "x-category": "Agents",
            "x-is-trigger": False, "x-display-name": "List Deleted Agents",
        },
        title="List Deleted Agents",
    )


class PhantomBusterGetContainerResultObjectConfig(BaseModel):
    """Retrieve the structured result object (the scraped data) for a run."""

    operation: Literal["get_container_result_object"] = Field(
        "get_container_result_object",
        json_schema_extra={
            "const": "get_container_result_object", "ui:hidden": True, "x-category": "Containers",
            "x-is-trigger": False, "x-display-name": "Get Container Result",
        },
        title="Get Container Result",
    )
    container_id: str = Field(
        ..., title="Container ID", description="The container (run) whose result object to fetch"
    )


class PhantomBusterUpdateUserConfig(BaseModel):
    """Update the current user's profile fields."""

    operation: Literal["update_user"] = Field(
        "update_user",
        json_schema_extra={
            "const": "update_user", "ui:hidden": True, "x-category": "Account",
            "x-is-trigger": False, "x-display-name": "Update Account",
        },
        title="Update Account",
    )
    user_payload: str = Field(
        ..., title="User Payload (JSON)",
        description="JSON object of profile fields to update (firstName, lastName, phone, company, job)",
        json_schema_extra={"ui:widget": "textarea"},
    )


class PhantomBusterListRunningContainersConfig(BaseModel):
    """List all currently-running containers across the organization."""

    operation: Literal["list_running_containers"] = Field(
        "list_running_containers",
        json_schema_extra={
            "const": "list_running_containers", "ui:hidden": True, "x-category": "Organization",
            "x-is-trigger": False, "x-display-name": "List Running Containers",
        },
        title="List Running Containers",
    )


class PhantomBusterListAgentGroupsConfig(BaseModel):
    """List the org's agent groups (folders)."""

    operation: Literal["list_agent_groups"] = Field(
        "list_agent_groups",
        json_schema_extra={
            "const": "list_agent_groups", "ui:hidden": True, "x-category": "Organization",
            "x-is-trigger": False, "x-display-name": "List Agent Groups",
        },
        title="List Agent Groups",
    )


class PhantomBusterGetLeadListConfig(BaseModel):
    """Fetch a single lead list by id."""

    operation: Literal["get_lead_list"] = Field(
        "get_lead_list",
        json_schema_extra={
            "const": "get_lead_list", "ui:hidden": True, "x-category": "Org Storage",
            "x-is-trigger": False, "x-display-name": "Get Lead List",
        },
        title="Get Lead List",
    )
    list_id: str = Field(..., title="List ID", description="The id of the lead list to fetch",
                         json_schema_extra=_LIST_DROPDOWN)


class PhantomBusterDeleteLeadListConfig(BaseModel):
    """Delete a lead list."""

    operation: Literal["delete_lead_list"] = Field(
        "delete_lead_list",
        json_schema_extra={
            "const": "delete_lead_list", "ui:hidden": True, "x-category": "Org Storage",
            "x-is-trigger": False, "x-display-name": "Delete Lead List",
        },
        title="Delete Lead List",
    )
    list_id: str = Field(..., title="List ID", description="The id of the lead list to delete",
                         json_schema_extra=_LIST_DROPDOWN)


class PhantomBusterSaveManyLeadsConfig(BaseModel):
    """Upsert multiple leads (1-20) into workspace storage in one call."""

    operation: Literal["save_many_leads"] = Field(
        "save_many_leads",
        json_schema_extra={
            "const": "save_many_leads", "ui:hidden": True, "x-category": "Org Storage",
            "x-is-trigger": False, "x-display-name": "Save Many Leads",
        },
        title="Save Many Leads",
    )
    leads_payload: str = Field(
        ..., title="Leads Payload (JSON)",
        description="JSON object with a leads array (1-20 records, each with linkedinProfileUrl)",
        json_schema_extra={"ui:widget": "textarea"},
    )


class PhantomBusterDeleteLeadsConfig(BaseModel):
    """Delete multiple leads by identifier."""

    operation: Literal["delete_leads"] = Field(
        "delete_leads",
        json_schema_extra={
            "const": "delete_leads", "ui:hidden": True, "x-category": "Org Storage",
            "x-is-trigger": False, "x-display-name": "Delete Leads",
        },
        title="Delete Leads",
    )
    leads_payload: str = Field(
        ..., title="Leads Payload (JSON)",
        description="JSON object identifying the leads to delete",
        json_schema_extra={"ui:widget": "textarea"},
    )


class PhantomBusterGetLeadsByListConfig(BaseModel):
    """Fetch the leads contained in a lead list."""

    operation: Literal["get_leads_by_list"] = Field(
        "get_leads_by_list",
        json_schema_extra={
            "const": "get_leads_by_list", "ui:hidden": True, "x-category": "Org Storage",
            "x-is-trigger": False, "x-display-name": "Get Leads By List",
        },
        title="Get Leads By List",
    )
    list_id: str = Field(..., title="List ID", description="The id of the lead list whose leads to fetch",
                         json_schema_extra=_LIST_DROPDOWN)


class PhantomBusterAiAdviceConfig(BaseModel):
    """Get AI advice (PhantomBuster-hosted AI)."""

    operation: Literal["ai_advice"] = Field(
        "ai_advice",
        json_schema_extra={
            "const": "ai_advice", "ui:hidden": True, "x-category": "AI & Utilities",
            "x-is-trigger": False, "x-display-name": "AI Advice",
        },
        title="AI Advice",
    )
    payload: str = Field(
        ..., title="Payload (JSON)", description="JSON request body for the AI advice call",
        json_schema_extra={"ui:widget": "textarea"},
    )


class PhantomBusterAiTaskConfig(BaseModel):
    """Run an AI task (PhantomBuster-hosted AI)."""

    operation: Literal["ai_task"] = Field(
        "ai_task",
        json_schema_extra={
            "const": "ai_task", "ui:hidden": True, "x-category": "AI & Utilities",
            "x-is-trigger": False, "x-display-name": "AI Task",
        },
        title="AI Task",
    )
    payload: str = Field(
        ..., title="Payload (JSON)", description="JSON request body for the AI task call",
        json_schema_extra={"ui:widget": "textarea"},
    )


class PhantomBusterSolveRecaptchaConfig(BaseModel):
    """Submit a reCAPTCHA challenge for solving."""

    operation: Literal["solve_recaptcha"] = Field(
        "solve_recaptcha",
        json_schema_extra={
            "const": "solve_recaptcha", "ui:hidden": True, "x-category": "AI & Utilities",
            "x-is-trigger": False, "x-display-name": "Solve reCAPTCHA",
        },
        title="Solve reCAPTCHA",
    )
    site_key: str = Field(..., title="Site Key", description="The reCAPTCHA site key for the challenge")
    page_url: str = Field(..., title="Page URL", description="The URL of the page presenting the reCAPTCHA")
    version: str = Field(
        "v2",
        title="Version",
        description="reCAPTCHA version",
        json_schema_extra={"enum": ["v2", "v3"], "enumNames": ["v2", "v3"], "x-enum-searchable": True},
    )


def _raw_payload_field(desc: str):
    return Field(..., title="Payload (JSON)", description=desc, json_schema_extra={"ui:widget": "textarea"})


def _raw_params_field(desc: str):
    return Field(None, title="Query Parameters (JSON)", description=desc, json_schema_extra={"ui:widget": "textarea"})


# --- Agents / Containers (extra) ---
class PhantomBusterUnscheduleAllConfig(BaseModel):
    """Remove all schedules from the org's agents."""

    operation: Literal["unschedule_all"] = Field(
        "unschedule_all",
        json_schema_extra={"const": "unschedule_all", "ui:hidden": True, "x-category": "Agents",
                           "x-is-trigger": False, "x-display-name": "Unschedule All Agents"},
        title="Unschedule All Agents",
    )


class PhantomBusterAttachContainerConfig(BaseModel):
    """Attach to a running container and return its live output stream."""

    operation: Literal["attach_container"] = Field(
        "attach_container",
        json_schema_extra={"const": "attach_container", "ui:hidden": True, "x-category": "Containers",
                           "x-is-trigger": False, "x-display-name": "Attach To Container"},
        title="Attach To Container",
    )
    container_id: str = Field(..., title="Container ID", description="The running container to attach to")


# --- Scripts (extra) ---
class PhantomBusterScriptVisibilityConfig(BaseModel):
    """Set a script's visibility."""

    operation: Literal["set_script_visibility"] = Field(
        "set_script_visibility",
        json_schema_extra={"const": "set_script_visibility", "ui:hidden": True, "x-category": "Scripts",
                           "x-is-trigger": False, "x-display-name": "Set Script Visibility"},
        title="Set Script Visibility",
    )
    payload: str = _raw_payload_field("JSON body, e.g. {\"id\": \"...\", \"visibility\": \"private|public|unlisted\"}")


class PhantomBusterScriptAccessListConfig(BaseModel):
    """Set a script's access list."""

    operation: Literal["set_script_access_list"] = Field(
        "set_script_access_list",
        json_schema_extra={"const": "set_script_access_list", "ui:hidden": True, "x-category": "Scripts",
                           "x-is-trigger": False, "x-display-name": "Set Script Access List"},
        title="Set Script Access List",
    )
    payload: str = _raw_payload_field("JSON body describing the script id and its access list")


# --- Branches (script versioning) ---
class PhantomBusterListBranchesConfig(BaseModel):
    """List script branches."""

    operation: Literal["list_branches"] = Field(
        "list_branches",
        json_schema_extra={"const": "list_branches", "ui:hidden": True, "x-category": "Branches",
                           "x-is-trigger": False, "x-display-name": "List Branches"},
        title="List Branches",
    )


class PhantomBusterDiffBranchConfig(BaseModel):
    """Diff a branch against production."""

    operation: Literal["diff_branch"] = Field(
        "diff_branch",
        json_schema_extra={"const": "diff_branch", "ui:hidden": True, "x-category": "Branches",
                           "x-is-trigger": False, "x-display-name": "Diff Branch"},
        title="Diff Branch",
    )
    name: str = Field(..., title="Branch Name", description="The branch to diff")


class PhantomBusterCreateBranchConfig(BaseModel):
    """Create a script branch."""

    operation: Literal["create_branch"] = Field(
        "create_branch",
        json_schema_extra={"const": "create_branch", "ui:hidden": True, "x-category": "Branches",
                           "x-is-trigger": False, "x-display-name": "Create Branch"},
        title="Create Branch",
    )
    payload: str = _raw_payload_field("JSON body describing the branch to create")


class PhantomBusterDeleteBranchConfig(BaseModel):
    """Delete a script branch."""

    operation: Literal["delete_branch"] = Field(
        "delete_branch",
        json_schema_extra={"const": "delete_branch", "ui:hidden": True, "x-category": "Branches",
                           "x-is-trigger": False, "x-display-name": "Delete Branch"},
        title="Delete Branch",
    )
    payload: str = _raw_payload_field("JSON body identifying the branch to delete")


class PhantomBusterReleaseBranchConfig(BaseModel):
    """Release (deploy) a branch to production."""

    operation: Literal["release_branch"] = Field(
        "release_branch",
        json_schema_extra={"const": "release_branch", "ui:hidden": True, "x-category": "Branches",
                           "x-is-trigger": False, "x-display-name": "Release Branch"},
        title="Release Branch",
    )
    payload: str = _raw_payload_field("JSON body describing the branch release")


# --- Organization (extra) ---
class PhantomBusterSaveAgentGroupsConfig(BaseModel):
    """Create/update the org's agent groups."""

    operation: Literal["save_agent_groups"] = Field(
        "save_agent_groups",
        json_schema_extra={"const": "save_agent_groups", "ui:hidden": True, "x-category": "Organization",
                           "x-is-trigger": False, "x-display-name": "Save Agent Groups"},
        title="Save Agent Groups",
    )
    payload: str = _raw_payload_field("JSON body describing the agent groups to save")


class PhantomBusterExportAgentUsageConfig(BaseModel):
    """Export per-agent usage as a report."""

    operation: Literal["export_agent_usage"] = Field(
        "export_agent_usage",
        json_schema_extra={"const": "export_agent_usage", "ui:hidden": True, "x-category": "Organization",
                           "x-is-trigger": False, "x-display-name": "Export Agent Usage"},
        title="Export Agent Usage",
    )
    query_params: Optional[str] = _raw_params_field("JSON of query params (e.g. date range) per the docs")


class PhantomBusterExportContainerUsageConfig(BaseModel):
    """Export per-container usage as a report."""

    operation: Literal["export_container_usage"] = Field(
        "export_container_usage",
        json_schema_extra={"const": "export_container_usage", "ui:hidden": True, "x-category": "Organization",
                           "x-is-trigger": False, "x-display-name": "Export Container Usage"},
        title="Export Container Usage",
    )
    query_params: Optional[str] = _raw_params_field("JSON of query params (e.g. date range) per the docs")


class PhantomBusterGetCrmAccessConfig(BaseModel):
    """Fetch the org's CRM integration access."""

    operation: Literal["get_crm_access"] = Field(
        "get_crm_access",
        json_schema_extra={"const": "get_crm_access", "ui:hidden": True, "x-category": "Organization",
                           "x-is-trigger": False, "x-display-name": "Get CRM Access"},
        title="Get CRM Access",
    )


class PhantomBusterGetCrmResourcesConfig(BaseModel):
    """Fetch the org's CRM resources."""

    operation: Literal["get_crm_resources"] = Field(
        "get_crm_resources",
        json_schema_extra={"const": "get_crm_resources", "ui:hidden": True, "x-category": "Organization",
                           "x-is-trigger": False, "x-display-name": "Get CRM Resources"},
        title="Get CRM Resources",
    )
    query_params: Optional[str] = _raw_params_field("JSON of query params per the docs (optional)")


class PhantomBusterSaveCrmContactConfig(BaseModel):
    """Upsert a CRM contact."""

    operation: Literal["save_crm_contact"] = Field(
        "save_crm_contact",
        json_schema_extra={"const": "save_crm_contact", "ui:hidden": True, "x-category": "Organization",
                           "x-is-trigger": False, "x-display-name": "Save CRM Contact"},
        title="Save CRM Contact",
    )
    payload: str = _raw_payload_field("JSON body describing the CRM contact to save")


# --- Identities (session/cookie management) ---
class PhantomBusterSaveIdentityConfig(BaseModel):
    """Save an identity (session cookies for logged-in scraping)."""

    operation: Literal["save_identity"] = Field(
        "save_identity",
        json_schema_extra={"const": "save_identity", "ui:hidden": True, "x-category": "Identities",
                           "x-is-trigger": False, "x-display-name": "Save Identity"},
        title="Save Identity",
    )
    payload: str = _raw_payload_field("JSON body describing the identity/session to save")


class PhantomBusterSaveIdentityWithTokenConfig(BaseModel):
    """Save an identity using a connection token."""

    operation: Literal["save_identity_with_token"] = Field(
        "save_identity_with_token",
        json_schema_extra={"const": "save_identity_with_token", "ui:hidden": True, "x-category": "Identities",
                           "x-is-trigger": False, "x-display-name": "Save Identity With Token"},
        title="Save Identity With Token",
    )
    payload: str = _raw_payload_field("JSON body including the connection token and identity data")


class PhantomBusterGenerateIdentityTokenConfig(BaseModel):
    """Generate a token + magic link for the user to connect an identity."""

    operation: Literal["generate_identity_token"] = Field(
        "generate_identity_token",
        json_schema_extra={"const": "generate_identity_token", "ui:hidden": True, "x-category": "Identities",
                           "x-is-trigger": False, "x-display-name": "Generate Identity Token"},
        title="Generate Identity Token",
    )


class PhantomBusterSearchIdentitiesConfig(BaseModel):
    """Search stored identities."""

    operation: Literal["search_identities"] = Field(
        "search_identities",
        json_schema_extra={"const": "search_identities", "ui:hidden": True, "x-category": "Identities",
                           "x-is-trigger": False, "x-display-name": "Search Identities"},
        title="Search Identities",
    )
    payload: Optional[str] = Field(
        None, title="Search Body (JSON)", description="Optional JSON search filter (empty returns all)",
        json_schema_extra={"ui:widget": "textarea"},
    )


class PhantomBusterSaveIdentityEventConfig(BaseModel):
    """Record an identity event."""

    operation: Literal["save_identity_event"] = Field(
        "save_identity_event",
        json_schema_extra={"const": "save_identity_event", "ui:hidden": True, "x-category": "Identities",
                           "x-is-trigger": False, "x-display-name": "Save Identity Event"},
        title="Save Identity Event",
    )
    payload: str = _raw_payload_field("JSON body describing the identity event")


# --- Strategic Resources ---
class PhantomBusterListIcpsConfig(BaseModel):
    """List Ideal Customer Profiles (ICPs)."""

    operation: Literal["list_icps"] = Field(
        "list_icps",
        json_schema_extra={"const": "list_icps", "ui:hidden": True, "x-category": "Strategic",
                           "x-is-trigger": False, "x-display-name": "List ICPs"},
        title="List ICPs",
    )


class PhantomBusterListBuyerPersonasConfig(BaseModel):
    """List buyer personas."""

    operation: Literal["list_buyer_personas"] = Field(
        "list_buyer_personas",
        json_schema_extra={"const": "list_buyer_personas", "ui:hidden": True, "x-category": "Strategic",
                           "x-is-trigger": False, "x-display-name": "List Buyer Personas"},
        title="List Buyer Personas",
    )


# --- Utility (extra) ---
class PhantomBusterSerpSearchConfig(BaseModel):
    """Run a SERP (search-engine results) scrape via BrightData."""

    operation: Literal["serp_search"] = Field(
        "serp_search",
        json_schema_extra={"const": "serp_search", "ui:hidden": True, "x-category": "AI & Utilities",
                           "x-is-trigger": False, "x-display-name": "SERP Search"},
        title="SERP Search",
    )
    query_params: str = Field(
        ..., title="Query Parameters (JSON)",
        description="JSON of the SERP query params per the docs (e.g. search terms / engine options)",
        json_schema_extra={"ui:widget": "textarea"},
    )


# ============================================================================
# Webhook Trigger Config (receiver — PhantomBuster webhooks are dashboard-only)
# ============================================================================


class PhantomBusterReceiveWebhookConfig(BaseModel):
    """Receive per-Phantom completion notifications from PhantomBuster."""

    model_config = ConfigDict(json_schema_extra={"x-requires-webhook": True})

    operation: Literal["receive_webhook"] = Field(
        "receive_webhook",
        json_schema_extra={
            "const": "receive_webhook",
            "ui:hidden": True,
            "x-category": None,
            "x-is-trigger": True,
            "x-display-name": "On Phantom Finished",
        },
        title="On Phantom Finished",
    )
    webhook_url: Optional[str] = Field(
        default=None,
        title="Webhook URL",
        description="Paste this URL into your Phantom's notification webhook setting; it POSTs run results here when the Phantom finishes.",
        json_schema_extra={
            "ui:widget": "webhook",
            "ui:copyable": True,
            "ui:loadValue": True,
        },
    )
    webhook_id: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})
    relay_connected: Optional[bool] = Field(default=None, json_schema_extra={"ui:hidden": True})
    is_production: Optional[bool] = Field(default=None, json_schema_extra={"ui:hidden": True})


# ============================================================================
# Discriminated Union
# ============================================================================


PhantomBusterConfig = Annotated[
    Union[
        PhantomBusterGetUserConfig,
        PhantomBusterUpdateUserConfig,
        PhantomBusterListAgentsConfig,
        PhantomBusterGetAgentConfig,
        PhantomBusterGetAgentOutputConfig,
        PhantomBusterListDeletedAgentsConfig,
        PhantomBusterLaunchAgentConfig,
        PhantomBusterLaunchAgentSoonConfig,
        PhantomBusterLaunchAgentSyncConfig,
        PhantomBusterStopAgentConfig,
        PhantomBusterSaveAgentConfig,
        PhantomBusterDeleteAgentConfig,
        PhantomBusterUnscheduleAllConfig,
        PhantomBusterListContainersConfig,
        PhantomBusterGetContainerConfig,
        PhantomBusterGetContainerOutputConfig,
        PhantomBusterGetContainerResultObjectConfig,
        PhantomBusterAttachContainerConfig,
        PhantomBusterListScriptsConfig,
        PhantomBusterGetScriptConfig,
        PhantomBusterGetScriptCodeConfig,
        PhantomBusterSaveScriptConfig,
        PhantomBusterDeleteScriptConfig,
        PhantomBusterScriptVisibilityConfig,
        PhantomBusterScriptAccessListConfig,
        PhantomBusterListBranchesConfig,
        PhantomBusterDiffBranchConfig,
        PhantomBusterCreateBranchConfig,
        PhantomBusterDeleteBranchConfig,
        PhantomBusterReleaseBranchConfig,
        PhantomBusterGetOrgConfig,
        PhantomBusterGetOrgResourcesConfig,
        PhantomBusterListRunningContainersConfig,
        PhantomBusterListAgentGroupsConfig,
        PhantomBusterSaveAgentGroupsConfig,
        PhantomBusterExportAgentUsageConfig,
        PhantomBusterExportContainerUsageConfig,
        PhantomBusterGetCrmAccessConfig,
        PhantomBusterGetCrmResourcesConfig,
        PhantomBusterSaveCrmContactConfig,
        PhantomBusterSaveLeadsConfig,
        PhantomBusterSaveManyLeadsConfig,
        PhantomBusterDeleteLeadsConfig,
        PhantomBusterGetLeadsByListConfig,
        PhantomBusterListLeadListsConfig,
        PhantomBusterGetLeadListConfig,
        PhantomBusterSaveLeadListConfig,
        PhantomBusterDeleteLeadListConfig,
        PhantomBusterSaveIdentityConfig,
        PhantomBusterSaveIdentityWithTokenConfig,
        PhantomBusterGenerateIdentityTokenConfig,
        PhantomBusterSearchIdentitiesConfig,
        PhantomBusterSaveIdentityEventConfig,
        PhantomBusterListIcpsConfig,
        PhantomBusterListBuyerPersonasConfig,
        PhantomBusterAiCompletionConfig,
        PhantomBusterAiAdviceConfig,
        PhantomBusterAiTaskConfig,
        PhantomBusterSolveHcaptchaConfig,
        PhantomBusterSolveRecaptchaConfig,
        PhantomBusterSerpSearchConfig,
        PhantomBusterIpLocationConfig,
        PhantomBusterReceiveWebhookConfig,
    ],
    Discriminator("operation"),
]


class PhantomBusterNodeConfig(NodeConfig[PhantomBusterConfig, PhantomBusterCredential]):
    """Full configuration for the PhantomBuster node including credentials."""

    pass


# ============================================================================
# HTTP Request Helper
# ============================================================================


async def _phantombuster_request(
    api_key: str,
    method: str,
    endpoint: str,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Dict[str, Any]] = None,
    action_name: str = "request",
) -> Dict[str, Any]:
    """Make an authenticated PhantomBuster v2 request and return a structured result."""
    url = f"{PHANTOMBUSTER_API_BASE}{endpoint}"
    headers = {
        "X-Phantombuster-Key-1": api_key,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if json_body:
        json_body = {k: v for k, v in json_body.items() if v is not None}
    if params:
        params = {k: v for k, v in params.items() if v not in (None, "")}

    start = time.time()
    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            response = await client.request(
                method=method, url=url, headers=headers, params=params, json=json_body
            )
            api_ms = round((time.time() - start) * 1000, 2)
            if response.status_code >= 400:
                try:
                    err = response.json()
                    message = (
                        err.get("error")
                        or err.get("message")
                        or str(err)
                        if isinstance(err, dict)
                        else str(err)
                    )
                except Exception:
                    message = response.text
                if isinstance(message, str):
                    message = message.encode("ascii", errors="replace").decode("ascii")
                logger.error(f"[PhantomBusterNode] API error ({action_name}): {message}")
                return {
                    "status": "error",
                    "action": action_name,
                    "error": message,
                    "status_code": response.status_code,
                    "timing_ms": {"api_request": api_ms},
                }
            if response.status_code == 204:
                data: Any = {"success": True}
            else:
                try:
                    data = response.json()
                except Exception:
                    data = {"raw": response.text}
            return {
                "status": "success",
                "action": action_name,
                "data": data,
                "status_code": response.status_code,
                "timing_ms": {"api_request": api_ms},
            }
        except httpx.TimeoutException:
            return {
                "status": "error",
                "action": action_name,
                "error": "Request timed out",
                "status_code": 408,
                "timing_ms": {"api_request": round((time.time() - start) * 1000, 2)},
            }
        except Exception as e:
            msg = str(e).encode("ascii", errors="replace").decode("ascii")
            logger.error(f"[PhantomBusterNode] Request failed ({action_name}): {msg}")
            return {
                "status": "error",
                "action": action_name,
                "error": msg,
                "status_code": 500,
                "timing_ms": {"api_request": round((time.time() - start) * 1000, 2)},
            }


def _parse_json_field(value: Optional[str]) -> Any:
    """Parse a JSON-string config field into a Python object. Raises on invalid JSON."""
    if value is None or value == "":
        return None
    import json

    return json.loads(value)


def _int_or_str(value: Optional[str]) -> Any:
    """Coerce a numeric config string to int for numeric API params; pass other
    non-empty strings through unchanged, and None for empty."""
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return value


def _parse_params(value: Optional[str]) -> Optional[Dict[str, Any]]:
    """Parse a JSON-object config string into a dict of query params. Raises on
    invalid JSON or a non-object. Used by raw query-param passthrough ops."""
    parsed = _parse_json_field(value)
    if parsed is None:
        return None
    if not isinstance(parsed, dict):
        raise ValueError("Query parameters must be a JSON object")
    return parsed


# ============================================================================
# Node Implementation
# ============================================================================


class PhantomBusterNode(WorkflowNode):
    """PhantomBuster web scraping & automation node."""

    edit_examples = [
        "List all my Phantoms",
        "Launch a LinkedIn scraping Phantom with custom arguments",
        "Get the output of a finished Phantom run",
        "Check my PhantomBuster account quota",
        "Trigger a workflow when a Phantom finishes running",
    ]

    @classmethod
    def get_config_model(cls):
        return PhantomBusterNodeConfig

    # ------------------------------------------------------------------
    # Webhook URL provisioning (dashboard-configured receiver)
    # ------------------------------------------------------------------
    @classmethod
    async def load_field_value(
        cls,
        field_name: str,
        user_id: str,
        workflow_id: UUID,
        node_id: str,
        pool,
        context: Optional[Dict[str, Any]] = None,
        credential_ids: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        if field_name != "webhook_url":
            return {"value": None}

        from utils.webhook_manager import WebhookManager

        webhook_data = await WebhookManager.get_or_create_webhook(
            pool=pool,
            user_id=user_id,
            workflow_id=workflow_id,
            node_id=node_id,
        )
        return {
            "values": {
                "webhook_id": webhook_data.get("webhook_id"),
                "webhook_url": webhook_data.get("webhook_url"),
                "relay_connected": webhook_data.get("relay_connected"),
                "is_production": webhook_data.get("is_production"),
            }
        }

    # ------------------------------------------------------------------
    # Dynamic options (agents, scripts, lead lists)
    # ------------------------------------------------------------------
    @classmethod
    async def load_field_options(
        cls,
        field_name: str,
        credential_data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        page_token: Optional[str] = None,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Load dropdown options for listable PhantomBuster resources.

        ``credential_data`` arrives already decrypted (and freshened) from the
        handler — read the api_key straight off it.
        """
        # field -> (list endpoint, action). Each returns a flat list of {id,name}
        # rows in v2 (possibly wrapped under data/agents/scripts/lists).
        loaders = {
            "agent_id": ("/agents/fetch-all", "list_agents"),
            "script_id": ("/scripts/fetch-all", "list_scripts"),
            "list_id": ("/org-storage/lists/fetch-all", "list_lead_lists"),
        }
        spec = loaders.get(field_name)
        if not spec:
            return {"options": []}
        api_key = (credential_data or {}).get("api_key")
        if not api_key:
            return {"options": []}

        endpoint, action = spec
        result = await _phantombuster_request(api_key, "GET", endpoint, action_name=action)
        if result.get("status") != "success":
            return {"options": []}
        data = result.get("data") or []
        if isinstance(data, dict):
            data = data.get("data") or data.get("agents") or data.get("scripts") or data.get("lists") or []
        options = []
        for row in data:
            if not isinstance(row, dict):
                continue
            row_id = row.get("id")
            if row_id is None:
                continue
            label = row.get("name") or row.get("title") or str(row_id)
            options.append({"label": str(label), "value": str(row_id)})
        return {"options": options}

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------
    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        start_time = time.time()
        config = self.config
        if not config or not isinstance(config, PhantomBusterNodeConfig):
            raise ValueError("Valid configuration is required")
        op = config.config

        if isinstance(op, PhantomBusterReceiveWebhookConfig):
            return {
                "status": "success",
                "action": "receive_webhook",
                "data": {**inputs, "webhook_url": op.webhook_url},
                "timing_ms": {"total": round((time.time() - start_time) * 1000, 2)},
            }

        credentials = config.credentials
        if not credentials:
            raise ValueError("Credentials are required. Add your PhantomBuster API key.")
        api_key = credentials.api_key

        handlers = {
            "get_user": self._get_user,
            "update_user": self._update_user,
            "list_agents": self._list_agents,
            "get_agent": self._get_agent,
            "get_agent_output": self._get_agent_output,
            "list_deleted_agents": self._list_deleted_agents,
            "launch_agent": self._launch_agent,
            "launch_agent_soon": self._launch_agent_soon,
            "launch_agent_sync": self._launch_agent_sync,
            "stop_agent": self._stop_agent,
            "save_agent": self._save_agent,
            "delete_agent": self._delete_agent,
            "unschedule_all": self._unschedule_all,
            "list_containers": self._list_containers,
            "get_container": self._get_container,
            "get_container_output": self._get_container_output,
            "get_container_result_object": self._get_container_result_object,
            "attach_container": self._attach_container,
            "list_scripts": self._list_scripts,
            "get_script": self._get_script,
            "get_script_code": self._get_script_code,
            "save_script": self._save_script,
            "delete_script": self._delete_script,
            "set_script_visibility": self._set_script_visibility,
            "set_script_access_list": self._set_script_access_list,
            "list_branches": self._list_branches,
            "diff_branch": self._diff_branch,
            "create_branch": self._create_branch,
            "delete_branch": self._delete_branch,
            "release_branch": self._release_branch,
            "get_org": self._get_org,
            "get_org_resources": self._get_org_resources,
            "list_running_containers": self._list_running_containers,
            "list_agent_groups": self._list_agent_groups,
            "save_agent_groups": self._save_agent_groups,
            "export_agent_usage": self._export_agent_usage,
            "export_container_usage": self._export_container_usage,
            "get_crm_access": self._get_crm_access,
            "get_crm_resources": self._get_crm_resources,
            "save_crm_contact": self._save_crm_contact,
            "save_leads": self._save_leads,
            "save_many_leads": self._save_many_leads,
            "delete_leads": self._delete_leads,
            "get_leads_by_list": self._get_leads_by_list,
            "list_lead_lists": self._list_lead_lists,
            "get_lead_list": self._get_lead_list,
            "save_lead_list": self._save_lead_list,
            "delete_lead_list": self._delete_lead_list,
            "save_identity": self._save_identity,
            "save_identity_with_token": self._save_identity_with_token,
            "generate_identity_token": self._generate_identity_token,
            "search_identities": self._search_identities,
            "save_identity_event": self._save_identity_event,
            "list_icps": self._list_icps,
            "list_buyer_personas": self._list_buyer_personas,
            "ai_completion": self._ai_completion,
            "ai_advice": self._ai_advice,
            "ai_task": self._ai_task,
            "solve_hcaptcha": self._solve_hcaptcha,
            "solve_recaptcha": self._solve_recaptcha,
            "serp_search": self._serp_search,
            "ip_location": self._ip_location,
        }
        handler = handlers.get(op.operation)
        if not handler:
            raise ValueError(f"Unknown operation: {op.operation}")

        result = await handler(op, api_key)
        result["timing_ms"] = {
            **result.get("timing_ms", {}),
            "total": round((time.time() - start_time) * 1000, 2),
        }
        return result

    # ------------------------------------------------------------------
    # Account handlers
    # ------------------------------------------------------------------
    async def _get_user(self, c: PhantomBusterGetUserConfig, api_key: str) -> Dict[str, Any]:
        return await _phantombuster_request(api_key, "GET", "/users/fetch-me", action_name="get_user")

    async def _update_user(self, c: PhantomBusterUpdateUserConfig, api_key: str) -> Dict[str, Any]:
        body = _parse_json_field(c.user_payload) or {}
        return await _phantombuster_request(
            api_key, "POST", "/users/update-me", json_body=body, action_name="update_user"
        )

    # ------------------------------------------------------------------
    # Agent handlers
    # ------------------------------------------------------------------
    async def _list_agents(self, c: PhantomBusterListAgentsConfig, api_key: str) -> Dict[str, Any]:
        return await _phantombuster_request(
            api_key, "GET", "/agents/fetch-all", action_name="list_agents"
        )

    async def _get_agent(self, c: PhantomBusterGetAgentConfig, api_key: str) -> Dict[str, Any]:
        return await _phantombuster_request(
            api_key, "GET", "/agents/fetch", params={"id": c.agent_id}, action_name="get_agent"
        )

    async def _get_agent_output(self, c: PhantomBusterGetAgentOutputConfig, api_key: str) -> Dict[str, Any]:
        return await _phantombuster_request(
            api_key, "GET", "/agents/fetch-output", params={"id": c.agent_id},
            action_name="get_agent_output",
        )

    async def _list_deleted_agents(self, c: PhantomBusterListDeletedAgentsConfig, api_key: str) -> Dict[str, Any]:
        return await _phantombuster_request(
            api_key, "GET", "/agents/fetch-deleted", action_name="list_deleted_agents"
        )

    async def _launch_agent(self, c: PhantomBusterLaunchAgentConfig, api_key: str) -> Dict[str, Any]:
        body = {"id": c.agent_id, "argument": _parse_json_field(c.argument)}
        return await _phantombuster_request(
            api_key, "POST", "/agents/launch", json_body=body, action_name="launch_agent"
        )

    async def _launch_agent_soon(
        self, c: PhantomBusterLaunchAgentSoonConfig, api_key: str
    ) -> Dict[str, Any]:
        body = {
            "id": c.agent_id,
            "minutes": _int_or_str(c.minutes),
            "argument": _parse_json_field(c.argument),
        }
        return await _phantombuster_request(
            api_key, "POST", "/agents/launch-soon", json_body=body, action_name="launch_agent_soon"
        )

    async def _launch_agent_sync(
        self, c: PhantomBusterLaunchAgentSyncConfig, api_key: str
    ) -> Dict[str, Any]:
        body = {"id": c.agent_id, "argument": _parse_json_field(c.argument)}
        return await _phantombuster_request(
            api_key, "POST", "/agents/launch-sync", json_body=body, action_name="launch_agent_sync"
        )

    async def _stop_agent(self, c: PhantomBusterStopAgentConfig, api_key: str) -> Dict[str, Any]:
        return await _phantombuster_request(
            api_key, "POST", "/agents/stop", json_body={"id": c.agent_id}, action_name="stop_agent"
        )

    async def _save_agent(self, c: PhantomBusterSaveAgentConfig, api_key: str) -> Dict[str, Any]:
        body = _parse_json_field(c.agent_payload) or {}
        return await _phantombuster_request(
            api_key, "POST", "/agents/save", json_body=body, action_name="save_agent"
        )

    async def _delete_agent(self, c: PhantomBusterDeleteAgentConfig, api_key: str) -> Dict[str, Any]:
        return await _phantombuster_request(
            api_key, "POST", "/agents/delete", json_body={"id": c.agent_id}, action_name="delete_agent"
        )

    # ------------------------------------------------------------------
    # Container handlers
    # ------------------------------------------------------------------
    async def _list_containers(
        self, c: PhantomBusterListContainersConfig, api_key: str
    ) -> Dict[str, Any]:
        return await _phantombuster_request(
            api_key, "GET", "/containers/fetch-all", params={"agentId": c.agent_id},
            action_name="list_containers",
        )

    async def _get_container(self, c: PhantomBusterGetContainerConfig, api_key: str) -> Dict[str, Any]:
        return await _phantombuster_request(
            api_key, "GET", "/containers/fetch", params={"id": c.container_id},
            action_name="get_container",
        )

    async def _get_container_output(
        self, c: PhantomBusterGetContainerOutputConfig, api_key: str
    ) -> Dict[str, Any]:
        return await _phantombuster_request(
            api_key, "GET", "/containers/fetch-output", params={"id": c.container_id},
            action_name="get_container_output",
        )

    async def _get_container_result_object(
        self, c: PhantomBusterGetContainerResultObjectConfig, api_key: str
    ) -> Dict[str, Any]:
        return await _phantombuster_request(
            api_key, "GET", "/containers/fetch-result-object", params={"id": c.container_id},
            action_name="get_container_result_object",
        )

    # ------------------------------------------------------------------
    # Script handlers
    # ------------------------------------------------------------------
    async def _list_scripts(self, c: PhantomBusterListScriptsConfig, api_key: str) -> Dict[str, Any]:
        return await _phantombuster_request(
            api_key, "GET", "/scripts/fetch-all", action_name="list_scripts"
        )

    async def _get_script(self, c: PhantomBusterGetScriptConfig, api_key: str) -> Dict[str, Any]:
        return await _phantombuster_request(
            api_key, "GET", "/scripts/fetch", params={"id": c.script_id}, action_name="get_script"
        )

    async def _get_script_code(
        self, c: PhantomBusterGetScriptCodeConfig, api_key: str
    ) -> Dict[str, Any]:
        return await _phantombuster_request(
            api_key, "GET", "/scripts/code", params={"id": c.script_id}, action_name="get_script_code"
        )

    async def _save_script(self, c: PhantomBusterSaveScriptConfig, api_key: str) -> Dict[str, Any]:
        body = _parse_json_field(c.script_payload) or {}
        return await _phantombuster_request(
            api_key, "POST", "/scripts/save", json_body=body, action_name="save_script"
        )

    async def _delete_script(self, c: PhantomBusterDeleteScriptConfig, api_key: str) -> Dict[str, Any]:
        return await _phantombuster_request(
            api_key, "POST", "/scripts/delete", json_body={"id": c.script_id},
            action_name="delete_script",
        )

    # ------------------------------------------------------------------
    # Organization handlers
    # ------------------------------------------------------------------
    async def _get_org(self, c: PhantomBusterGetOrgConfig, api_key: str) -> Dict[str, Any]:
        return await _phantombuster_request(api_key, "GET", "/orgs/fetch", action_name="get_org")

    async def _get_org_resources(
        self, c: PhantomBusterGetOrgResourcesConfig, api_key: str
    ) -> Dict[str, Any]:
        return await _phantombuster_request(
            api_key, "GET", "/orgs/fetch-resources", action_name="get_org_resources"
        )

    async def _list_running_containers(
        self, c: PhantomBusterListRunningContainersConfig, api_key: str
    ) -> Dict[str, Any]:
        return await _phantombuster_request(
            api_key, "GET", "/orgs/fetch-running-containers", action_name="list_running_containers"
        )

    async def _list_agent_groups(
        self, c: PhantomBusterListAgentGroupsConfig, api_key: str
    ) -> Dict[str, Any]:
        return await _phantombuster_request(
            api_key, "GET", "/orgs/fetch-agent-groups", action_name="list_agent_groups"
        )

    # ------------------------------------------------------------------
    # Org storage handlers
    # ------------------------------------------------------------------
    async def _save_leads(self, c: PhantomBusterSaveLeadsConfig, api_key: str) -> Dict[str, Any]:
        body = _parse_json_field(c.leads_payload)
        json_body = body if isinstance(body, dict) else {"leads": body}
        return await _phantombuster_request(
            api_key, "POST", "/org-storage/leads/save", json_body=json_body, action_name="save_leads"
        )

    async def _save_many_leads(self, c: PhantomBusterSaveManyLeadsConfig, api_key: str) -> Dict[str, Any]:
        body = _parse_json_field(c.leads_payload) or {}
        return await _phantombuster_request(
            api_key, "POST", "/org-storage/leads/save-many", json_body=body, action_name="save_many_leads"
        )

    async def _delete_leads(self, c: PhantomBusterDeleteLeadsConfig, api_key: str) -> Dict[str, Any]:
        body = _parse_json_field(c.leads_payload) or {}
        return await _phantombuster_request(
            api_key, "POST", "/org-storage/leads/delete-many", json_body=body, action_name="delete_leads"
        )

    async def _get_leads_by_list(self, c: PhantomBusterGetLeadsByListConfig, api_key: str) -> Dict[str, Any]:
        return await _phantombuster_request(
            api_key, "POST", f"/org-storage/leads/by-list/{c.list_id}", json_body={},
            action_name="get_leads_by_list",
        )

    async def _list_lead_lists(
        self, c: PhantomBusterListLeadListsConfig, api_key: str
    ) -> Dict[str, Any]:
        return await _phantombuster_request(
            api_key, "GET", "/org-storage/lists/fetch-all", action_name="list_lead_lists"
        )

    async def _get_lead_list(self, c: PhantomBusterGetLeadListConfig, api_key: str) -> Dict[str, Any]:
        return await _phantombuster_request(
            api_key, "GET", "/org-storage/lists/fetch", params={"id": c.list_id},
            action_name="get_lead_list",
        )

    async def _save_lead_list(self, c: PhantomBusterSaveLeadListConfig, api_key: str) -> Dict[str, Any]:
        body = _parse_json_field(c.list_payload) or {}
        return await _phantombuster_request(
            api_key, "POST", "/org-storage/lists/save", json_body=body, action_name="save_lead_list"
        )

    async def _delete_lead_list(self, c: PhantomBusterDeleteLeadListConfig, api_key: str) -> Dict[str, Any]:
        return await _phantombuster_request(
            api_key, "POST", "/org-storage/lists/delete", json_body={"id": c.list_id},
            action_name="delete_lead_list",
        )

    # ------------------------------------------------------------------
    # AI / utility handlers
    # ------------------------------------------------------------------
    async def _ai_completion(self, c: PhantomBusterAiCompletionConfig, api_key: str) -> Dict[str, Any]:
        # Live-verified: /ai/completions takes a chat `messages` array, not a bare prompt.
        body = {"messages": [{"role": "user", "content": c.prompt}]}
        return await _phantombuster_request(
            api_key, "POST", "/ai/completions", json_body=body, action_name="ai_completion",
        )

    async def _ai_advice(self, c: PhantomBusterAiAdviceConfig, api_key: str) -> Dict[str, Any]:
        body = _parse_json_field(c.payload) or {}
        return await _phantombuster_request(
            api_key, "POST", "/ai/advice", json_body=body, action_name="ai_advice"
        )

    async def _ai_task(self, c: PhantomBusterAiTaskConfig, api_key: str) -> Dict[str, Any]:
        body = _parse_json_field(c.payload) or {}
        return await _phantombuster_request(
            api_key, "POST", "/ai/tasks", json_body=body, action_name="ai_task"
        )

    async def _solve_hcaptcha(self, c: PhantomBusterSolveHcaptchaConfig, api_key: str) -> Dict[str, Any]:
        # Live-verified: /hcaptcha takes {"key": <site key>, "url": <page url>}.
        body = {"key": c.site_key, "url": c.page_url}
        return await _phantombuster_request(
            api_key, "POST", "/hcaptcha", json_body=body, action_name="solve_hcaptcha"
        )

    async def _solve_recaptcha(self, c: PhantomBusterSolveRecaptchaConfig, api_key: str) -> Dict[str, Any]:
        # Live-verified: /recaptcha takes {"key", "url", "type"} (type = v2/v3).
        body = {"key": c.site_key, "url": c.page_url, "type": c.version}
        return await _phantombuster_request(
            api_key, "POST", "/recaptcha", json_body=body, action_name="solve_recaptcha"
        )

    async def _ip_location(self, c: PhantomBusterIpLocationConfig, api_key: str) -> Dict[str, Any]:
        return await _phantombuster_request(
            api_key, "GET", "/location/ip", params={"ip": c.ip}, action_name="ip_location"
        )

    # ------------------------------------------------------------------
    # Agents / Containers (extra)
    # ------------------------------------------------------------------
    async def _unschedule_all(self, c: PhantomBusterUnscheduleAllConfig, api_key: str) -> Dict[str, Any]:
        return await _phantombuster_request(
            api_key, "POST", "/agents/unschedule-all", json_body={}, action_name="unschedule_all"
        )

    async def _attach_container(self, c: PhantomBusterAttachContainerConfig, api_key: str) -> Dict[str, Any]:
        return await _phantombuster_request(
            api_key, "GET", "/containers/attach", params={"id": c.container_id},
            action_name="attach_container",
        )

    # ------------------------------------------------------------------
    # Scripts (extra) + Branches
    # ------------------------------------------------------------------
    async def _set_script_visibility(self, c: PhantomBusterScriptVisibilityConfig, api_key: str) -> Dict[str, Any]:
        return await _phantombuster_request(
            api_key, "POST", "/scripts/visibility", json_body=_parse_json_field(c.payload) or {},
            action_name="set_script_visibility",
        )

    async def _set_script_access_list(self, c: PhantomBusterScriptAccessListConfig, api_key: str) -> Dict[str, Any]:
        return await _phantombuster_request(
            api_key, "POST", "/scripts/access-list", json_body=_parse_json_field(c.payload) or {},
            action_name="set_script_access_list",
        )

    async def _list_branches(self, c: PhantomBusterListBranchesConfig, api_key: str) -> Dict[str, Any]:
        return await _phantombuster_request(api_key, "GET", "/branches/fetch-all", action_name="list_branches")

    async def _diff_branch(self, c: PhantomBusterDiffBranchConfig, api_key: str) -> Dict[str, Any]:
        return await _phantombuster_request(
            api_key, "GET", "/branches/diff", params={"name": c.name}, action_name="diff_branch"
        )

    async def _create_branch(self, c: PhantomBusterCreateBranchConfig, api_key: str) -> Dict[str, Any]:
        return await _phantombuster_request(
            api_key, "POST", "/branches/create", json_body=_parse_json_field(c.payload) or {},
            action_name="create_branch",
        )

    async def _delete_branch(self, c: PhantomBusterDeleteBranchConfig, api_key: str) -> Dict[str, Any]:
        return await _phantombuster_request(
            api_key, "POST", "/branches/delete", json_body=_parse_json_field(c.payload) or {},
            action_name="delete_branch",
        )

    async def _release_branch(self, c: PhantomBusterReleaseBranchConfig, api_key: str) -> Dict[str, Any]:
        return await _phantombuster_request(
            api_key, "POST", "/branches/release", json_body=_parse_json_field(c.payload) or {},
            action_name="release_branch",
        )

    # ------------------------------------------------------------------
    # Organization (extra)
    # ------------------------------------------------------------------
    async def _save_agent_groups(self, c: PhantomBusterSaveAgentGroupsConfig, api_key: str) -> Dict[str, Any]:
        return await _phantombuster_request(
            api_key, "POST", "/orgs/save-agent-groups", json_body=_parse_json_field(c.payload) or {},
            action_name="save_agent_groups",
        )

    async def _export_agent_usage(self, c: PhantomBusterExportAgentUsageConfig, api_key: str) -> Dict[str, Any]:
        return await _phantombuster_request(
            api_key, "GET", "/orgs/export-agent-usage", params=_parse_params(c.query_params),
            action_name="export_agent_usage",
        )

    async def _export_container_usage(self, c: PhantomBusterExportContainerUsageConfig, api_key: str) -> Dict[str, Any]:
        return await _phantombuster_request(
            api_key, "GET", "/orgs/export-container-usage", params=_parse_params(c.query_params),
            action_name="export_container_usage",
        )

    async def _get_crm_access(self, c: PhantomBusterGetCrmAccessConfig, api_key: str) -> Dict[str, Any]:
        return await _phantombuster_request(api_key, "GET", "/orgs/fetch-crm-access", action_name="get_crm_access")

    async def _get_crm_resources(self, c: PhantomBusterGetCrmResourcesConfig, api_key: str) -> Dict[str, Any]:
        return await _phantombuster_request(
            api_key, "GET", "/orgs/fetch-crm-resources", params=_parse_params(c.query_params),
            action_name="get_crm_resources",
        )

    async def _save_crm_contact(self, c: PhantomBusterSaveCrmContactConfig, api_key: str) -> Dict[str, Any]:
        return await _phantombuster_request(
            api_key, "POST", "/orgs/save-crm-contact", json_body=_parse_json_field(c.payload) or {},
            action_name="save_crm_contact",
        )

    # ------------------------------------------------------------------
    # Identities
    # ------------------------------------------------------------------
    async def _save_identity(self, c: PhantomBusterSaveIdentityConfig, api_key: str) -> Dict[str, Any]:
        return await _phantombuster_request(
            api_key, "POST", "/identities/save", json_body=_parse_json_field(c.payload) or {},
            action_name="save_identity",
        )

    async def _save_identity_with_token(self, c: PhantomBusterSaveIdentityWithTokenConfig, api_key: str) -> Dict[str, Any]:
        return await _phantombuster_request(
            api_key, "POST", "/identities/save-with-token", json_body=_parse_json_field(c.payload) or {},
            action_name="save_identity_with_token",
        )

    async def _generate_identity_token(self, c: PhantomBusterGenerateIdentityTokenConfig, api_key: str) -> Dict[str, Any]:
        return await _phantombuster_request(
            api_key, "POST", "/identities/generate-token", json_body={}, action_name="generate_identity_token"
        )

    async def _search_identities(self, c: PhantomBusterSearchIdentitiesConfig, api_key: str) -> Dict[str, Any]:
        return await _phantombuster_request(
            api_key, "POST", "/identities/search", json_body=_parse_json_field(c.payload) or {},
            action_name="search_identities",
        )

    async def _save_identity_event(self, c: PhantomBusterSaveIdentityEventConfig, api_key: str) -> Dict[str, Any]:
        return await _phantombuster_request(
            api_key, "POST", "/identities/events/save", json_body=_parse_json_field(c.payload) or {},
            action_name="save_identity_event",
        )

    # ------------------------------------------------------------------
    # Strategic Resources + Utility (extra)
    # ------------------------------------------------------------------
    async def _list_icps(self, c: PhantomBusterListIcpsConfig, api_key: str) -> Dict[str, Any]:
        return await _phantombuster_request(api_key, "GET", "/icps/fetch-all", action_name="list_icps")

    async def _list_buyer_personas(self, c: PhantomBusterListBuyerPersonasConfig, api_key: str) -> Dict[str, Any]:
        return await _phantombuster_request(
            api_key, "GET", "/buyers-personas/fetch-all", action_name="list_buyer_personas"
        )

    async def _serp_search(self, c: PhantomBusterSerpSearchConfig, api_key: str) -> Dict[str, Any]:
        return await _phantombuster_request(
            api_key, "GET", "/brightdata/serp", params=_parse_params(c.query_params),
            action_name="serp_search",
        )
