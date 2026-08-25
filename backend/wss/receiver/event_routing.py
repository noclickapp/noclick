"""
Event routing configuration for socket events.
This defines which handler processes each event type in each environment.
Single source of truth for both the receiver and type generation.
"""

from enum import Enum
from typing import Dict, List


class Handler(Enum):
    """Enumeration of all available handlers."""
    AGENT = "agent_handler"
    YPY = "ypy_handler"
    CACHE_VALTIO = "cache_valtio_handler"
    USAGE_DASHBOARD = "usage_dashboard_handler"
    WORKFLOW_EXECUTION = "workflow_execution_handler"
    WORKFLOW = "workflow_handler"
    WORKFLOW_MCP = "workflow_mcp_handler"
    CREDENTIALS = "credentials_handler"
    GOOGLE_OAUTH = "google_oauth_handler"
    AIRTABLE_OAUTH = "airtable_oauth_handler"
    STRIPE_OAUTH = "stripe_oauth_handler"
    ATLASSIAN_OAUTH = "atlassian_oauth_handler"
    CANVA_OAUTH = "canva_oauth_handler"
    DISCORD_OAUTH = "discord_oauth_handler"
    DROPBOX_OAUTH = "dropbox_oauth_handler"
    FACEBOOK_OAUTH = "facebook_oauth_handler"
    THREADS_OAUTH = "threads_oauth_handler"
    INSTAGRAM_LOGIN_OAUTH = "instagram_login_oauth_handler"
    FACEBOOK_PAGES_OAUTH = "facebook_pages_oauth_handler"
    META_OAUTH = "meta_oauth_handler"
    FATHOM_OAUTH = "fathom_oauth_handler"
    GITHUB_OAUTH = "github_oauth_handler"
    HUBSPOT_OAUTH = "hubspot_oauth_handler"
    MAILCHIMP_OAUTH = "mailchimp_oauth_handler"
    TYPEFORM_OAUTH = "typeform_oauth_handler"
    SUPABASE_OAUTH = "supabase_oauth_handler"
    ZOOM_OAUTH = "zoom_oauth_handler"
    LINEAR_OAUTH = "linear_oauth_handler"
    QUICKBOOKS_OAUTH = "quickbooks_oauth_handler"
    CALENDLY_OAUTH = "calendly_oauth_handler"
    SENTRY_OAUTH = "sentry_oauth_handler"
    POSTHOG_OAUTH = "posthog_oauth_handler"
    CALCOM_OAUTH = "calcom_oauth_handler"
    GITLAB_OAUTH = "gitlab_oauth_handler"
    BOX_OAUTH = "box_oauth_handler"
    ASANA_OAUTH = "asana_oauth_handler"
    MONDAY_OAUTH = "monday_oauth_handler"
    ATTIO_OAUTH = "attio_oauth_handler"
    INTERCOM_OAUTH = "intercom_oauth_handler"
    PIPEDRIVE_OAUTH = "pipedrive_oauth_handler"
    PAGERDUTY_OAUTH = "pagerduty_oauth_handler"
    WEBFLOW_OAUTH = "webflow_oauth_handler"
    LINKEDIN_OAUTH = "linkedin_oauth_handler"
    CLICKUP_OAUTH = "clickup_oauth_handler"
    ZENDESK_OAUTH = "zendesk_oauth_handler"
    BAMBOOHR_OAUTH = "bamboohr_oauth_handler"
    KLAVIYO_OAUTH = "klaviyo_oauth_handler"
    MICROSOFT_OAUTH = "microsoft_oauth_handler"
    NOTION_OAUTH = "notion_oauth_handler"
    REDDIT_OAUTH = "reddit_oauth_handler"
    SALESFORCE_OAUTH = "salesforce_oauth_handler"
    SHOPIFY_OAUTH = "shopify_oauth_handler"
    SLACK_OAUTH = "slack_oauth_handler"
    TWITTER_OAUTH = "twitter_oauth_handler"
    TIKTOK_OAUTH = "tiktok_oauth_handler"
    WORDPRESS_OAUTH = "wordpress_oauth_handler"
    PARALLEL_OAUTH = "parallel_oauth_handler"
    MCP_OAUTH = "mcp_oauth_handler"
    CLOUDFLARE_OAUTH = "cloudflare_oauth_handler"
    APOLLO_OAUTH = "apollo_oauth_handler"
    SAVED_OUTPUT = "saved_output_handler"
    ORGANIZATION = "organization_handler"
    WORKFLOW_CHECKPOINT = "workflow_checkpoint_handler"
    SHARE = "share_handler"
    ONBOARDING = "onboarding_handler"
    NOTIFICATION_PREFS = "notification_prefs_handler"
    INSTANCE_OAUTH = "instance_oauth_handler"
    WORKFLOW_BUILDER = "workflow_builder_handler"
    FOLDER = "folder_handler"
    RESOURCE = "resource_handler"
    CODEX_AUTH = "codex_auth_handler"
    CLAUDE_CODE_AUTH = "claude_code_auth_handler"
    WHATSAPP_QR = "whatsapp_qr_handler"
    FEED = "feed_handler"
    SKILL = "skill_handler"
    FEEDBACK = "feedback_handler"
    AGENT_SHARE = "agent_share_handler"
    AGENT_WORKSPACE = "agent_workspace_handler"


# Event routing configuration - maps environments to events and their handlers
EVENT_ROUTING: Dict[str, Dict[str, Handler]] = {
    "API": {
        # Chat and agent events
        "chat:message": Handler.AGENT,
        "agent:update_model": Handler.AGENT, # TODO: this event is likely deprecated
        "agent:set:cwd": Handler.AGENT,
        "agent:pause": Handler.AGENT,
        "agent:builder_decision": Handler.AGENT,  # approve/dismiss verdict on a prompt_builder card

        # Conversation management events
        "conversations:list": Handler.WORKFLOW_BUILDER,
        "conversation:resume": Handler.WORKFLOW_BUILDER,
        "conversation:delete": Handler.WORKFLOW_BUILDER,
        "conversation:get_latest_for_workflow": Handler.WORKFLOW_BUILDER,
        "conversation:list_for_agent": Handler.WORKFLOW_BUILDER,

        # Onboarding events
        "onboarding:submit": Handler.ONBOARDING,
        "onboarding:skip": Handler.ONBOARDING,
        "onboarding:completion:get": Handler.ONBOARDING,
        "onboarding:completion:update": Handler.ONBOARDING,

        # Notification email preferences
        "notifications:prefs:get": Handler.NOTIFICATION_PREFS,
        "notifications:prefs:update": Handler.NOTIFICATION_PREFS,
        "instance_oauth:list": Handler.INSTANCE_OAUTH,
        "instance_oauth:set": Handler.INSTANCE_OAUTH,
        "instance_oauth:delete": Handler.INSTANCE_OAUTH,

        # In-app feedback / bug report
        "feedback:submit": Handler.FEEDBACK,

        # Credentials events
        "credential:create": Handler.CREDENTIALS,
        "credential:list": Handler.CREDENTIALS,
        "credential:get": Handler.CREDENTIALS,
        "credential:display_info": Handler.CREDENTIALS,
        "credential:authorize_for_workflow": Handler.CREDENTIALS,
        "credential:update": Handler.CREDENTIALS,
        "credential:delete": Handler.CREDENTIALS,
        "credential:request:create": Handler.CREDENTIALS,
        "credential:request:list": Handler.CREDENTIALS,
        "credential:request:cancel": Handler.CREDENTIALS,
        "credential:validate_access": Handler.CREDENTIALS,

        # Google OAuth events
        "google:oauth:exchange": Handler.GOOGLE_OAUTH,
        "google:oauth:refresh": Handler.GOOGLE_OAUTH,
        "google:oauth:validate": Handler.GOOGLE_OAUTH,

        # Airtable OAuth events
        "airtable:oauth:exchange": Handler.AIRTABLE_OAUTH,
        "airtable:oauth:refresh": Handler.AIRTABLE_OAUTH,
        "airtable:oauth:validate": Handler.AIRTABLE_OAUTH,

        # Stripe OAuth events
        "stripe:oauth:exchange": Handler.STRIPE_OAUTH,
        "stripe:oauth:refresh": Handler.STRIPE_OAUTH,
        "stripe:oauth:validate": Handler.STRIPE_OAUTH,

        # GitHub OAuth events
        "github:oauth:exchange": Handler.GITHUB_OAUTH,
        "github:oauth:refresh": Handler.GITHUB_OAUTH,
        "github:oauth:validate": Handler.GITHUB_OAUTH,

        # Atlassian OAuth events (Jira)
        "atlassian:oauth:exchange": Handler.ATLASSIAN_OAUTH,
        "atlassian:oauth:refresh": Handler.ATLASSIAN_OAUTH,
        "atlassian:oauth:validate": Handler.ATLASSIAN_OAUTH,

        # Canva OAuth events
        "canva:oauth:exchange": Handler.CANVA_OAUTH,
        "canva:oauth:refresh": Handler.CANVA_OAUTH,
        "canva:oauth:validate": Handler.CANVA_OAUTH,

        # Discord OAuth events
        "discord:oauth:exchange": Handler.DISCORD_OAUTH,
        "discord:oauth:refresh": Handler.DISCORD_OAUTH,
        "discord:oauth:validate": Handler.DISCORD_OAUTH,

        # Dropbox OAuth events
        "dropbox:oauth:exchange": Handler.DROPBOX_OAUTH,
        "dropbox:oauth:refresh": Handler.DROPBOX_OAUTH,
        "dropbox:oauth:validate": Handler.DROPBOX_OAUTH,

        # Facebook OAuth events (Instagram integration)
        "facebook:oauth:exchange": Handler.FACEBOOK_OAUTH,
        "facebook:oauth:refresh": Handler.FACEBOOK_OAUTH,
        "facebook:oauth:validate": Handler.FACEBOOK_OAUTH,
        "threads:oauth:exchange": Handler.THREADS_OAUTH,
        "threads:oauth:refresh": Handler.THREADS_OAUTH,
        "threads:oauth:validate": Handler.THREADS_OAUTH,
        "facebook_pages:oauth:exchange": Handler.FACEBOOK_PAGES_OAUTH,
        "facebook_pages:oauth:refresh": Handler.FACEBOOK_PAGES_OAUTH,
        "facebook_pages:oauth:validate": Handler.FACEBOOK_PAGES_OAUTH,
        "meta:oauth:exchange": Handler.META_OAUTH,
        "meta:oauth:refresh": Handler.META_OAUTH,
        "meta:oauth:validate": Handler.META_OAUTH,

        # Fathom OAuth events
        "fathom:oauth:exchange": Handler.FATHOM_OAUTH,
        "fathom:oauth:refresh": Handler.FATHOM_OAUTH,
        "fathom:oauth:validate": Handler.FATHOM_OAUTH,

        # HubSpot OAuth events
        "hubspot:oauth:exchange": Handler.HUBSPOT_OAUTH,
        "hubspot:oauth:refresh": Handler.HUBSPOT_OAUTH,
        "hubspot:oauth:validate": Handler.HUBSPOT_OAUTH,

        # Mailchimp OAuth events (tokens don't expire, no refresh needed)
        "mailchimp:oauth:exchange": Handler.MAILCHIMP_OAUTH,

        # Typeform OAuth events
        "typeform:oauth:exchange": Handler.TYPEFORM_OAUTH,
        "typeform:oauth:refresh": Handler.TYPEFORM_OAUTH,
        "typeform:oauth:validate": Handler.TYPEFORM_OAUTH,
        "supabase:oauth:exchange": Handler.SUPABASE_OAUTH,
        "supabase:oauth:refresh": Handler.SUPABASE_OAUTH,
        "supabase:oauth:validate": Handler.SUPABASE_OAUTH,
        "supabase:oauth:select_project": Handler.SUPABASE_OAUTH,

        # WordPress OAuth events
        "wordpress:oauth:exchange": Handler.WORDPRESS_OAUTH,
        "wordpress:oauth:refresh": Handler.WORDPRESS_OAUTH,
        "wordpress:oauth:validate": Handler.WORDPRESS_OAUTH,

        # Parallel OAuth events
        "parallel:oauth:exchange": Handler.PARALLEL_OAUTH,
        "parallel:oauth:validate": Handler.PARALLEL_OAUTH,
        # Zoom OAuth events
        "zoom:oauth:exchange": Handler.ZOOM_OAUTH,
        "zoom:oauth:refresh": Handler.ZOOM_OAUTH,
        "zoom:oauth:validate": Handler.ZOOM_OAUTH,
        # Apollo OAuth events
        "apollo:oauth:exchange": Handler.APOLLO_OAUTH,
        "apollo:oauth:refresh": Handler.APOLLO_OAUTH,
        "apollo:oauth:validate": Handler.APOLLO_OAUTH,

        # Linear OAuth events
        "linear:oauth:exchange": Handler.LINEAR_OAUTH,
        "linear:oauth:refresh": Handler.LINEAR_OAUTH,
        "linear:oauth:validate": Handler.LINEAR_OAUTH,
        "calcom:oauth:exchange": Handler.CALCOM_OAUTH,
        "calcom:oauth:refresh": Handler.CALCOM_OAUTH,
        "calcom:oauth:validate": Handler.CALCOM_OAUTH,

        # GitLab OAuth events
        "gitlab:oauth:exchange": Handler.GITLAB_OAUTH,
        "gitlab:oauth:refresh": Handler.GITLAB_OAUTH,
        "gitlab:oauth:validate": Handler.GITLAB_OAUTH,
        # Box OAuth events
        "box:oauth:exchange": Handler.BOX_OAUTH,
        "box:oauth:refresh": Handler.BOX_OAUTH,
        "box:oauth:validate": Handler.BOX_OAUTH,

        # Asana OAuth events
        "asana:oauth:exchange": Handler.ASANA_OAUTH,
        "asana:oauth:refresh": Handler.ASANA_OAUTH,
        "asana:oauth:validate": Handler.ASANA_OAUTH,

        # Monday OAuth events
        "monday:oauth:exchange": Handler.MONDAY_OAUTH,
        "monday:oauth:refresh": Handler.MONDAY_OAUTH,
        "monday:oauth:validate": Handler.MONDAY_OAUTH,

        # Attio OAuth events
        "attio:oauth:exchange": Handler.ATTIO_OAUTH,
        "attio:oauth:refresh": Handler.ATTIO_OAUTH,
        "attio:oauth:validate": Handler.ATTIO_OAUTH,

        # Intercom OAuth events
        "intercom:oauth:exchange": Handler.INTERCOM_OAUTH,
        "intercom:oauth:refresh": Handler.INTERCOM_OAUTH,
        "intercom:oauth:validate": Handler.INTERCOM_OAUTH,

        # Pipedrive OAuth events
        "pipedrive:oauth:exchange": Handler.PIPEDRIVE_OAUTH,
        "pipedrive:oauth:refresh": Handler.PIPEDRIVE_OAUTH,
        "pipedrive:oauth:validate": Handler.PIPEDRIVE_OAUTH,

        # PagerDuty OAuth events
        "pagerduty:oauth:exchange": Handler.PAGERDUTY_OAUTH,
        "pagerduty:oauth:refresh": Handler.PAGERDUTY_OAUTH,
        "pagerduty:oauth:validate": Handler.PAGERDUTY_OAUTH,

        # Webflow OAuth events
        "webflow:oauth:exchange": Handler.WEBFLOW_OAUTH,
        "webflow:oauth:refresh": Handler.WEBFLOW_OAUTH,
        "webflow:oauth:validate": Handler.WEBFLOW_OAUTH,

        # QuickBooks OAuth events
        "quickbooks:oauth:exchange": Handler.QUICKBOOKS_OAUTH,
        "quickbooks:oauth:refresh": Handler.QUICKBOOKS_OAUTH,
        "quickbooks:oauth:validate": Handler.QUICKBOOKS_OAUTH,
        # Calendly OAuth events
        "calendly:oauth:exchange": Handler.CALENDLY_OAUTH,
        "calendly:oauth:refresh": Handler.CALENDLY_OAUTH,
        "calendly:oauth:validate": Handler.CALENDLY_OAUTH,
        # Sentry OAuth events
        "sentry:oauth:exchange": Handler.SENTRY_OAUTH,
        "sentry:oauth:refresh": Handler.SENTRY_OAUTH,
        "sentry:oauth:validate": Handler.SENTRY_OAUTH,
        # PostHog OAuth events
        "posthog:oauth:exchange": Handler.POSTHOG_OAUTH,
        "posthog:oauth:refresh": Handler.POSTHOG_OAUTH,
        "posthog:oauth:validate": Handler.POSTHOG_OAUTH,

        # LinkedIn OAuth events
        "linkedin:oauth:exchange": Handler.LINKEDIN_OAUTH,
        "linkedin:oauth:refresh": Handler.LINKEDIN_OAUTH,
        "linkedin:oauth:validate": Handler.LINKEDIN_OAUTH,
        # Zendesk OAuth events
        "zendesk:oauth:exchange": Handler.ZENDESK_OAUTH,
        "zendesk:oauth:refresh": Handler.ZENDESK_OAUTH,
        "zendesk:oauth:validate": Handler.ZENDESK_OAUTH,
        "bamboohr:oauth:exchange": Handler.BAMBOOHR_OAUTH,
        "bamboohr:oauth:refresh": Handler.BAMBOOHR_OAUTH,
        "bamboohr:oauth:validate": Handler.BAMBOOHR_OAUTH,
        "klaviyo:oauth:exchange": Handler.KLAVIYO_OAUTH,
        "klaviyo:oauth:refresh": Handler.KLAVIYO_OAUTH,
        "klaviyo:oauth:validate": Handler.KLAVIYO_OAUTH,

        # ClickUp OAuth events
        "clickup:oauth:exchange": Handler.CLICKUP_OAUTH,
        "clickup:oauth:refresh": Handler.CLICKUP_OAUTH,
        "clickup:oauth:validate": Handler.CLICKUP_OAUTH,

        # Microsoft OAuth events
        "microsoft:oauth:exchange": Handler.MICROSOFT_OAUTH,
        "microsoft:oauth:refresh": Handler.MICROSOFT_OAUTH,
        "microsoft:oauth:validate": Handler.MICROSOFT_OAUTH,

        # Notion OAuth events
        "notion:oauth:exchange": Handler.NOTION_OAUTH,
        "notion:oauth:refresh": Handler.NOTION_OAUTH,
        "notion:oauth:validate": Handler.NOTION_OAUTH,

        # MCP OAuth events (for connecting to external MCP servers)
        "mcp:oauth:discover": Handler.MCP_OAUTH,
        "mcp:oauth:exchange": Handler.MCP_OAUTH,
        "mcp:oauth:register-client": Handler.MCP_OAUTH,

        # Reddit OAuth events
        "reddit:oauth:exchange": Handler.REDDIT_OAUTH,
        "reddit:oauth:refresh": Handler.REDDIT_OAUTH,
        "reddit:oauth:validate": Handler.REDDIT_OAUTH,

        # Salesforce OAuth events
        "salesforce:oauth:exchange": Handler.SALESFORCE_OAUTH,
        "salesforce:oauth:refresh": Handler.SALESFORCE_OAUTH,
        "salesforce:oauth:validate": Handler.SALESFORCE_OAUTH,

        # Shopify OAuth events
        "shopify:oauth:exchange": Handler.SHOPIFY_OAUTH,
        "shopify:oauth:refresh": Handler.SHOPIFY_OAUTH,
        "shopify:oauth:validate": Handler.SHOPIFY_OAUTH,

        # Slack OAuth events
        "slack:oauth:exchange": Handler.SLACK_OAUTH,
        "slack:oauth:refresh": Handler.SLACK_OAUTH,
        "slack:oauth:validate": Handler.SLACK_OAUTH,

        # Twitter OAuth events
        "twitter:oauth:exchange": Handler.TWITTER_OAUTH,
        "twitter:oauth:refresh": Handler.TWITTER_OAUTH,
        "twitter:oauth:validate": Handler.TWITTER_OAUTH,

        # TikTok OAuth events
        "tiktok:oauth:exchange": Handler.TIKTOK_OAUTH,
        "tiktok:oauth:refresh": Handler.TIKTOK_OAUTH,
        "tiktok:oauth:validate": Handler.TIKTOK_OAUTH,

        # Cloudflare OAuth events
        "cloudflare:oauth:exchange": Handler.CLOUDFLARE_OAUTH,
        "cloudflare:oauth:refresh": Handler.CLOUDFLARE_OAUTH,
        "cloudflare:oauth:validate": Handler.CLOUDFLARE_OAUTH,

        # Usage dashboard events
        "usage:data": Handler.USAGE_DASHBOARD,
        "usage:logs": Handler.USAGE_DASHBOARD,

        # Workflow operations
        "workflow:create": Handler.WORKFLOW,
        "workflow:list": Handler.WORKFLOW,
        "workflow:get": Handler.WORKFLOW,
        "workflow:update": Handler.WORKFLOW,
        "workflow:node:set_config": Handler.WORKFLOW,
        "workflow:node:get_config": Handler.WORKFLOW,
        "workflow:state:get": Handler.WORKFLOW,
        "workflow:state:set": Handler.WORKFLOW,
        "workflow:state:keys": Handler.WORKFLOW,
        "workflow:delete": Handler.WORKFLOW,
        "workflow:restore": Handler.WORKFLOW,
        "workflow:list_trash": Handler.WORKFLOW,
        "workflow:permanent_delete": Handler.WORKFLOW,
        "workflow:list_executions": Handler.WORKFLOW,
        "workflow:get_execution_counts": Handler.WORKFLOW,
        "workflow:get_execution_detail": Handler.WORKFLOW,
        "workflow:get_node_output": Handler.WORKFLOW,
        "workflow:stop": Handler.WORKFLOW_EXECUTION,
        "workflow:execute": Handler.WORKFLOW_EXECUTION,
        "workflow:node:validate_config": Handler.WORKFLOW,
        "workflow:node:evaluate_expression": Handler.WORKFLOW,
        "workflow:node:get_config_schema": Handler.WORKFLOW,
        "workflow:node:load_options": Handler.WORKFLOW,
        "credential:test_connection": Handler.WORKFLOW,
        "rehearsal:run": Handler.WORKFLOW,
        "rehearsal:scenarios": Handler.WORKFLOW,
        "workflow:node:load_value": Handler.WORKFLOW,
        "email:check_local_part": Handler.WORKFLOW,
        "email:reserve_address": Handler.WORKFLOW,
        "workflow:node:schema": Handler.WORKFLOW,
        "workflow:collab_token": Handler.WORKFLOW,
        "workflow:clear_node_state": Handler.WORKFLOW,
        "workflow:save_node_state": Handler.WORKFLOW,
        "workflow:load_node_state": Handler.WORKFLOW,
        "workflow:get_node_outputs": Handler.WORKFLOW_MCP,
        "workflow:get_node_output_history": Handler.WORKFLOW_MCP,

        # Workflow folder operations
        "workflow_folder:create": Handler.FOLDER,
        "workflow_folder:list": Handler.FOLDER,
        "workflow_folder:get": Handler.FOLDER,
        "workflow_folder:update": Handler.FOLDER,
        "workflow_folder:delete": Handler.FOLDER,
        "workflow_folder:get_tree": Handler.FOLDER,
        "workflow_folder:get_path": Handler.FOLDER,
        "workflow_folder:move_workflow": Handler.FOLDER,

        # MCP folder operations (exposed via MCP adapter)
        "workflow:mcp:get_folder_tree": Handler.FOLDER,

        # Webhook relay operations (local dev only)
    
        # Workflow builder (AI-powered workflow editing)
        "workflow:builder:edit": Handler.WORKFLOW_BUILDER,
        "workflow:builder:autofill": Handler.WORKFLOW_BUILDER,
        "workflow:builder:input_response": Handler.WORKFLOW_BUILDER,
        "workflow:builder:list_pending": Handler.WORKFLOW_BUILDER,
        "workflow:builder:share_ask": Handler.WORKFLOW_BUILDER,
        "workflow:builder:get_state": Handler.WORKFLOW_BUILDER,
        "workflow:builder:usage": Handler.WORKFLOW_BUILDER,

        # Saved output operations (mock data management)
        "saved_output:create": Handler.SAVED_OUTPUT,
        "saved_output:list": Handler.SAVED_OUTPUT,
        "saved_output:get": Handler.SAVED_OUTPUT,
        "saved_output:update": Handler.SAVED_OUTPUT,
        "saved_output:delete": Handler.SAVED_OUTPUT,

        # Resource sharing operations
        "share:create": Handler.SHARE,
        "share:list": Handler.SHARE,
        "share:update": Handler.SHARE,
        "share:delete": Handler.SHARE,
        "share:leave": Handler.SHARE,
        "share:list_shared_with_me": Handler.SHARE,
        "share:invite_link": Handler.SHARE,
        "share:invite_accept": Handler.SHARE,

        # Shared agent link operations (owner-side manage + anonymous visitor chat)
        "agent_share:get_or_create": Handler.AGENT_SHARE,
        "agent_share:rotate": Handler.AGENT_SHARE,
        "agent_share:set_active": Handler.AGENT_SHARE,
        "run_share:create": Handler.AGENT_SHARE,
        "shared_agent:send": Handler.AGENT_SHARE,
        "shared_agent:resume": Handler.AGENT_SHARE,

        # Agent workspace file view (chat file rail + preview links)
        "agent_workspace:list": Handler.AGENT_WORKSPACE,

        # Resource forking operations
        "resource:fork": Handler.SHARE,

        # Workflow template operations (public template library)

        # Workflow checkpoint operations (version control)
        "workflow:checkpoint:create": Handler.WORKFLOW_CHECKPOINT,
        "workflow:checkpoint:list": Handler.WORKFLOW_CHECKPOINT,
        "workflow:checkpoint:restore": Handler.WORKFLOW_CHECKPOINT,
        "workflow:checkpoint:delete": Handler.WORKFLOW_CHECKPOINT,

        # Workflow resource operations (datasets, blobs)
        "resource:create": Handler.RESOURCE,
        "resource:list": Handler.RESOURCE,
        "resource:get": Handler.RESOURCE,
        "resource:delete": Handler.RESOURCE,
        "resource:upload_url": Handler.RESOURCE,
        "resource:download_url": Handler.RESOURCE,
        "resource:dataset:rows": Handler.RESOURCE,
        "resource:dataset:append": Handler.RESOURCE,
        "resource:dataset:update_row": Handler.RESOURCE,
        "resource:dataset:delete_rows": Handler.RESOURCE,

        # Skill operations (agent-context skills: description + optional text/workflow)
        "skill:list": Handler.SKILL,
        "skill:get": Handler.SKILL,
        "skill:create": Handler.SKILL,
        "skill:update": Handler.SKILL,
        "skill:delete": Handler.SKILL,
        "skill:mute": Handler.SKILL,
        "skill:get_workflow": Handler.SKILL,
        "skill:update_workflow": Handler.SKILL,

        # Setup flow events (guided template onboarding)

        # Debug operations (query timing and performance metrics - developers only)

        # Trigger Tests (internal-only Debug tab + 12h scheduled worker — runs the
        # live OAuth refresh and trigger renewal paths against real providers)

        # Analytics operations (internal team metrics - developers only)

        # Workflow MCP operations (for AI agent workflow manipulation)
        "workflow:mcp:response": Handler.WORKFLOW_MCP,
        "workflow:mcp:search_nodes": Handler.WORKFLOW_MCP,
        "workflow:mcp:get_node_config_schema": Handler.WORKFLOW_MCP,
        "workflow:mcp:get_selected_node": Handler.WORKFLOW_MCP,
        "workflow:mcp:get_open_workflow": Handler.WORKFLOW_MCP,
        "workflow:mcp:get_node_output": Handler.WORKFLOW_MCP,
        "workflow:mcp:get_node_input": Handler.WORKFLOW_MCP,
        "workflow:mcp:run_workflow": Handler.WORKFLOW_MCP,
        "workflow:mcp:create_workflow": Handler.WORKFLOW_MCP,
        "workflow:mcp:open_workflow": Handler.WORKFLOW_MCP,
        "workflow:mcp:list_workflows": Handler.WORKFLOW_MCP,
        "workflow:mcp:delete_workflow": Handler.WORKFLOW_MCP,
        "workflow:mcp:update_workflow_metadata": Handler.WORKFLOW_MCP,
        "workflow:mcp:list_saved_outputs": Handler.WORKFLOW_MCP,
        "workflow:mcp:run_node": Handler.WORKFLOW_MCP,
        "workflow:mcp:get_execution_status": Handler.WORKFLOW_MCP,
        "workflow:mcp:list_credentials": Handler.WORKFLOW_MCP,
        "workflow:mcp:load_field_options": Handler.WORKFLOW_MCP,
        "workflow:mcp:get_node_config": Handler.WORKFLOW_MCP,
        "workflow:mcp:update_interface": Handler.WORKFLOW_MCP,

        # YJS sync events
        "yjs:sync": Handler.YPY,

        # Organization operations
        "organization:create": Handler.ORGANIZATION,
        "organization:get": Handler.ORGANIZATION,
        "organization:update": Handler.ORGANIZATION,
        "organization:delete": Handler.ORGANIZATION,
        "organization:list_mine": Handler.ORGANIZATION,
        "organization:switch": Handler.ORGANIZATION,
        "organization:upload_icon": Handler.ORGANIZATION,
        "organization:members:list": Handler.ORGANIZATION,
        "organization:members:invite": Handler.ORGANIZATION,
        "organization:members:remove": Handler.ORGANIZATION,
        "organization:members:update_role": Handler.ORGANIZATION,
        "organization:transfer_ownership": Handler.ORGANIZATION,
        "organization:invites:list": Handler.ORGANIZATION,
        "organization:invites:get": Handler.ORGANIZATION,
        "organization:invites:accept": Handler.ORGANIZATION,
        "organization:invites:revoke": Handler.ORGANIZATION,
        "organization:sso:configure": Handler.ORGANIZATION,
        "organization:sso:disable": Handler.ORGANIZATION,
        "organization:sso:info": Handler.ORGANIZATION,
        "organization:check_slug": Handler.ORGANIZATION,

        # Codex device code auth events
        "codex:auth:start": Handler.CODEX_AUTH,
        "codex:auth:poll": Handler.CODEX_AUTH,

        # Claude Code OAuth PKCE auth events
        "claude-code:auth:start": Handler.CLAUDE_CODE_AUTH,
        "claude-code:auth:exchange": Handler.CLAUDE_CODE_AUTH,



        # WhatsApp QR code auth events
        "whatsapp:qr:start": Handler.WHATSAPP_QR,
        "whatsapp:qr:status": Handler.WHATSAPP_QR,

        # Approval feed events
        "approval:list": Handler.FEED,
        "approval:respond": Handler.FEED,

        # Activity log events
        "activity:list": Handler.FEED,

        # Agent tool-call feed
        "tool_calls:list": Handler.FEED,

        # Publishing events
    },
}


# Lifecycle handlers configuration - handlers that need lifecycle management but don't handle events directly
# These handlers will have setup_user() and cleanup_user() called but won't receive events
# Note: Handlers that are already in EVENT_ROUTING shouldn't be here to avoid duplicate lifecycle calls
LIFECYCLE_HANDLERS: Dict[str, List[Handler]] = {
    "API": [
        Handler.CACHE_VALTIO,  # Manages Redis persistence for YJS state
    ],
}


def get_all_events() -> Dict[str, str]:
    """
    Get all events with their primary environment.
    Used for TypeScript generation.
    """
    event_map = {}
    for event in EVENT_ROUTING.get("API", {}):
        event_map[event] = "API"
    return event_map


def get_handler_for_event(env: str, event: str) -> Handler:
    """
    Get the handler enum for a specific event in a given environment.

    Args:
        env: The environment (e.g. "API")
        event: The event name

    Returns:
        The Handler for this event, or None if not found
    """
    return EVENT_ROUTING.get(env, {}).get(event)
