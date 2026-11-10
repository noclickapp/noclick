"""
Node registry for dynamically loading workflow node classes.

Provides a centralized registry that maps node types to their implementation classes
and handles instantiation of nodes based on type.
"""

import logging
from pathlib import Path
from typing import Dict, Optional, Type, Any
from nodes.core.base import WorkflowNode
from nodes.core.discovery import discover_nodes, merge_node_entries
from nodes.telegram_node import TelegramNode
from nodes.phone_node import PhoneNode
from nodes.agent_node import AgentNode
from nodes.google_sheets_node import GoogleSheetsNode
from nodes.google_drive_node import GoogleDriveNode
from nodes.gmail_node import GmailNode
from nodes.iteration_node import IterationNode
from nodes.delay_node import DelayNode
from nodes.http_request_node import HttpRequestNode
from nodes.linear_node import LinearNode
from nodes.github_rest_node import GithubRestNode
from nodes.stripe_node import StripeNode
from nodes.cron_trigger_node import CronTriggerNode
from nodes.discord_node import DiscordNode
from nodes.dummy_node import DummyNode
from nodes.google_calendar_node import GoogleCalendarNode
from nodes.google_forms_node import GoogleFormsNode
from nodes.hubspot_node import HubSpotNode
from nodes.instagram_node import InstagramNode
from nodes.facebook_node import FacebookNode
from nodes.meta_node import MetaNode
from nodes.instantly_node import InstantlyNode
from nodes.jira_node import JiraNode
from nodes.notion_node import NotionNode
from nodes.outlook_mail_node import OutlookMailNode
from nodes.redis_node import RedisNode
from nodes.salesforce_node import SalesforceNode
from nodes.serverless_function_node import ServerlessFunctionNode
from nodes.shopify_node import ShopifyNode
from nodes.slack_node import SlackNode
from nodes.tool_node import ToolNode
from nodes.mcp_server_node import MCPServerNode
from nodes.noclick_node import NoClickNode
from nodes.alarm_node import AlarmNode
from nodes.filesystem_node import FilesystemNode
from nodes.cloudflare_node import CloudflareNode
from nodes.twilio_node import TwilioNode
from nodes.webhook_trigger_node import WebhookTriggerNode
from nodes.inbound_email_trigger_node import InboundEmailTriggerNode
from nodes.send_email_node import SendEmailNode
from nodes.table_node import TableNode
from nodes.run_trigger_node import RunTriggerNode
from nodes.submit_external_form_node import SubmitExternalFormNode
from nodes.pipedrive_node import PipedriveNode
from nodes.resend_node import ResendNode
from nodes.phantombuster_node import PhantomBusterNode
from nodes.cal_com_node import CalComNode
from nodes.calendly_node import CalendlyNode
from nodes.honeycomb_node import HoneycombNode
from nodes.sentry_node import SentryNode
from nodes.perplexity_node import PerplexityNode
from nodes.posthog_node import PostHogNode
from nodes.atlas_admin_node import AtlasAdminNode
from nodes.mailgun_node import MailgunNode
from nodes.gitlab_node import GitLabNode
from nodes.box_node import BoxNode
from nodes.clickup_node import ClickUpNode
from nodes.devin_node import DevinNode
from nodes.asana_node import AsanaNode
from nodes.firestore_node import FirestoreNode
from nodes.google_cloud_storage_node import GoogleCloudStorageNode
from nodes.monday_node import MondayNode
from nodes.parallel_node import ParallelNode
from nodes.datadog_node import DatadogNode
from nodes.loops_node import LoopsNode
from nodes.exa_node import ExaNode
from nodes.reducto_node import ReductoNode
from nodes.fal_node import FalNode
from nodes.brandfetch_node import BrandfetchNode
from nodes.findymail_node import FindymailNode
from nodes.beehiiv_node import BeehiivNode
from nodes.hex_node import HexNode
from nodes.clickhouse_node import ClickHouseNode
from nodes.extend_node import ExtendNode
from nodes.fellow_node import FellowNode
from nodes.fathom_node import FathomNode
from nodes.sigma_node import SigmaNode
from nodes.trello_node import TrelloNode
from nodes.firecrawl_node import FirecrawlNode
from nodes.attio_node import AttioNode
from nodes.intercom_node import IntercomNode
from nodes.zendesk_node import ZendeskNode
from nodes.confluence_node import ConfluenceNode
from nodes.pagerduty_node import PagerDutyNode
from nodes.google_meet_node import GoogleMeetNode
from nodes.expensify_node import ExpensifyNode
from nodes.freshsales_node import FreshsalesNode
from nodes.launchdarkly_node import LaunchDarklyNode
from nodes.appsheet_node import AppSheetNode
from nodes.tableau_node import TableauNode
from nodes.webflow_node import WebflowNode
from nodes.google_translate_node import GoogleTranslateNode
from nodes.bigquery_node import BigQueryNode
from nodes.snowflake_node import SnowflakeNode
from nodes.databricks_node import DatabricksNode
from nodes.microsoft_teams_node import MicrosoftTeamsNode
from nodes.gohighlevel_node import GoHighLevelNode
from nodes.quickbooks_node import QuickBooksNode
from nodes.zoom_node import ZoomNode
from nodes.klaviyo_node import KlaviyoNode
from nodes.onelake_node import OneLakeNode
from nodes.threads_node import ThreadsNode
from nodes.bamboohr_node import BambooHRNode
from nodes.dv360_node import DV360Node
from nodes.typeform_node import TypeformNode
from nodes.filter_node import FilterNode
from nodes.split_out_node import SplitOutNode
from nodes.conditional_node import ConditionalNode
from nodes.switch_node import SwitchNode
from nodes.merge_node import MergeNode
from nodes.state_manager_node import StateManagerNode
from nodes.on_error_node import OnErrorNode
from nodes.set_variable_node import SetVariableNode
from nodes.approval_node import ApprovalNode
from nodes.log_node import LogNode
from nodes.whatsapp_node import WhatsAppNode
from nodes.interface import (
    FormInterfaceNode,
    FileInterfaceNode,
    DataframeInterfaceNode,
    HtmlReactInterfaceNode,
    FileUploadInterfaceNode,
)

logger = logging.getLogger(__name__)


# Registry mapping node types to their implementation classes
_NODE_REGISTRY_ENTRIES: Dict[str, Type[WorkflowNode]] = {
    # Trigger nodes (entry points for workflows)
    'trigger-run': RunTriggerNode,
    'trigger-webhook': WebhookTriggerNode,
    'trigger-email': InboundEmailTriggerNode,
    'trigger-cron': CronTriggerNode,

    # Automation nodes
    'automation-telegram': TelegramNode,
    'automation-phone': PhoneNode,
    'automation-http-request': HttpRequestNode,
    'automation-linear': LinearNode,
    'automation-github-rest': GithubRestNode,
    'automation-stripe': StripeNode,
    'automation-discord': DiscordNode,
    'automation-hubspot': HubSpotNode,
    'automation-instagram': InstagramNode,
    'automation-facebook': FacebookNode,
    'automation-meta': MetaNode,
    'automation-instantly': InstantlyNode,
    'automation-jira': JiraNode,
    'automation-notion': NotionNode,
    'automation-redis': RedisNode,
    'automation-salesforce': SalesforceNode,
    'automation-shopify': ShopifyNode,
    'automation-slack': SlackNode,
    'automation-pipedrive': PipedriveNode,
    'automation-resend': ResendNode,
    'automation-threads': ThreadsNode,
    'automation-phantombuster': PhantomBusterNode,
    'automation-cal-com': CalComNode,
    'automation-calendly': CalendlyNode,
    'automation-honeycomb': HoneycombNode,
    'automation-sentry': SentryNode,
    'automation-perplexity': PerplexityNode,
    'automation-posthog': PostHogNode,
    'automation-atlas-admin': AtlasAdminNode,
    'automation-mailgun': MailgunNode,
    'automation-gitlab': GitLabNode,
    'automation-box': BoxNode,
    'automation-clickup': ClickUpNode,
    'automation-devin': DevinNode,
    'automation-asana': AsanaNode,
    'automation-firestore': FirestoreNode,
    'automation-google-cloud-storage': GoogleCloudStorageNode,
    'automation-monday': MondayNode,
    'automation-parallel': ParallelNode,
    'automation-datadog': DatadogNode,
    'automation-loops': LoopsNode,
    'automation-exa': ExaNode,
    'automation-reducto': ReductoNode,
    'automation-fal': FalNode,
    'automation-brandfetch': BrandfetchNode,
    'automation-findymail': FindymailNode,
    'automation-beehiiv': BeehiivNode,
    'automation-hex': HexNode,
    'automation-clickhouse': ClickHouseNode,
    'automation-extend': ExtendNode,
    'automation-fellow': FellowNode,
    'automation-fathom': FathomNode,
    'automation-sigma': SigmaNode,
    'automation-trello': TrelloNode,
    'automation-firecrawl': FirecrawlNode,
    'automation-attio': AttioNode,
    'automation-intercom': IntercomNode,
    'automation-zendesk': ZendeskNode,
    'automation-confluence': ConfluenceNode,
    'automation-pagerduty': PagerDutyNode,
    'automation-google-meet': GoogleMeetNode,
    'automation-expensify': ExpensifyNode,
    'automation-freshsales': FreshsalesNode,
    'automation-launchdarkly': LaunchDarklyNode,
    'automation-appsheet': AppSheetNode,
    'automation-tableau': TableauNode,
    'automation-webflow': WebflowNode,
    'automation-google-translate': GoogleTranslateNode,
    'automation-bigquery': BigQueryNode,
    'automation-snowflake': SnowflakeNode,
    'automation-databricks': DatabricksNode,
    'automation-microsoft-teams': MicrosoftTeamsNode,
    'automation-gohighlevel': GoHighLevelNode,
    'automation-quickbooks': QuickBooksNode,
    'automation-zoom': ZoomNode,
    'automation-klaviyo': KlaviyoNode,
    'automation-onelake': OneLakeNode,
    'automation-bamboohr': BambooHRNode,
    'automation-dv360': DV360Node,
    'automation-send-email': SendEmailNode,
    'automation-table': TableNode,
    'automation-typeform': TypeformNode,
    'automation-twilio': TwilioNode,
    'automation-cloudflare': CloudflareNode,
    'automation-whatsapp': WhatsAppNode,

    # Google integrations
    'automation-google-sheets': GoogleSheetsNode,
    'automation-google-drive': GoogleDriveNode,
    'automation-gmail': GmailNode,
    'automation-google-calendar': GoogleCalendarNode,
    'automation-google-forms': GoogleFormsNode,

    # Microsoft integrations
    'automation-outlook': OutlookMailNode,

    # AI Agent nodes
    'agent': AgentNode,
    'tool': ToolNode,
    'mcp-server': MCPServerNode,
    'noclick': NoClickNode,
    'alarm': AlarmNode,
    'filesystem': FilesystemNode,

    # Control flow nodes
    'iteration': IterationNode,
    'delay': DelayNode,
    'filter': FilterNode,
    'split-out': SplitOutNode,
    'conditional': ConditionalNode,
    'switch': SwitchNode,
    'merge': MergeNode,
    'approval': ApprovalNode,
    'log': LogNode,
    'automation-submit-external-form': SubmitExternalFormNode,

    # Compute nodes
    'automation-serverless-function': ServerlessFunctionNode,

    # State management nodes
    'state-manager': StateManagerNode,

    # Setup node (entry point for guided template onboarding)

    # On-error node (runs when workflow execution encounters an error)
    'on-error': OnErrorNode,

    # Set variable node (stores values as global variables)
    'set-variable': SetVariableNode,

    # Interface nodes (UI components for the workflow interface builder)
    'interface-form': FormInterfaceNode,
    'interface-file': FileInterfaceNode,
    'interface-dataframe': DataframeInterfaceNode,
    'interface-html-react': HtmlReactInterfaceNode,
    'interface-file-upload': FileUploadInterfaceNode,

    # Test nodes (for testing only)
    'test-dummy': DummyNode,
}

# Backward-compat: the separate image/audio/video interface nodes were merged into
# the universal File/Multimedia node (interface-file) in 2026-07. Resolve the old
# types to it on lookup so pre-merge saved workflows keep rendering/executing. The
# aliases resolve on get/[]/in ONLY — they are NOT part of iteration, so schema and
# MCP-tool generation (which walk NODE_REGISTRY.items()) never re-emit the old types.
LEGACY_NODE_TYPE_ALIASES: Dict[str, str] = {
    'interface-image': 'interface-file',
    'interface-audio': 'interface-file',
    'interface-video': 'interface-file',
    # 2026-07: the form trigger and the config form merged into the unified form
    # node — interface-form carries the public link + trigger fire path AND the
    # persistent config.values store itself.
    'trigger-form-input': 'interface-form',
    'interface-config-form': 'interface-form',
}


def resolve_node_type(node_type: Optional[str]) -> Optional[str]:
    """Canonical node type, resolving legacy aliases.

    Saved graphs may still carry pre-merge type strings; stored-graph type
    checks must compare against this, never the raw string.
    """
    if node_type is None:
        return None
    return LEGACY_NODE_TYPE_ALIASES.get(node_type, node_type)


class _NodeRegistry(Dict[str, Type[WorkflowNode]]):
    """dict that resolves LEGACY_NODE_TYPE_ALIASES on lookup but not on iteration."""

    def get(self, key, default=None):  # type: ignore[override]
        if dict.__contains__(self, key):
            return dict.__getitem__(self, key)
        alias = LEGACY_NODE_TYPE_ALIASES.get(key)
        if alias is not None and dict.__contains__(self, alias):
            return dict.__getitem__(self, alias)
        return default

    def __getitem__(self, key):
        if dict.__contains__(self, key):
            return dict.__getitem__(self, key)
        alias = LEGACY_NODE_TYPE_ALIASES.get(key)
        if alias is not None:
            return dict.__getitem__(self, alias)
        raise KeyError(key)

    def __contains__(self, key):
        if dict.__contains__(self, key):
            return True
        alias = LEGACY_NODE_TYPE_ALIASES.get(key)
        return alias is not None and dict.__contains__(self, alias)


from nodes.core.oauth_registry import oauth_providers, validate_oauth_credential_types

DISCOVERED_NODE_ENTRIES = discover_nodes(Path(__file__).resolve().parents[1])
NODE_REGISTRY: Dict[str, Type[WorkflowNode]] = _NodeRegistry(
    merge_node_entries(_NODE_REGISTRY_ENTRIES, DISCOVERED_NODE_ENTRIES)
)
validate_oauth_credential_types(oauth_providers(), NODE_REGISTRY.values())

# Node types that use the SDK for inter-node communication — edges to/from them are rejected.
# Derived from WorkflowNode.connectionless class attribute (single source of truth).
CONNECTIONLESS_TYPES: frozenset[str] = frozenset(
    ntype for ntype, cls in NODE_REGISTRY.items() if getattr(cls, 'connectionless', False)
)


def validate_edge(source_type: str, target_type: str) -> str | None:
    """Return an error string if this edge is invalid, or None if OK."""
    if source_type in CONNECTIONLESS_TYPES:
        return f"Cannot add edge from {source_type}: uses SDK for communication, not edges"
    if target_type in CONNECTIONLESS_TYPES:
        return f"Cannot add edge to {target_type}: uses SDK for communication, not edges"
    return None


class NodeFactory:
    """
    Factory for creating workflow node instances.

    Handles dynamic instantiation of node classes based on their type.
    """

    @staticmethod
    def create_node(
        node_id: str,
        node_type: str,
        node_data: Dict[str, Any],
        sio=None,
        sid: str = None,
        workflow_id: str = None,
        user_id: str = None,
        conversation_id: str = None,
        organization_id: str = None,
        execution_id: str = None
    ) -> WorkflowNode:
        """
        Create a workflow node instance based on its type.

        Parses the node_data into a typed Pydantic config model before
        passing it to the node constructor, allowing nodes to use
        config during initialization.

        Args:
            node_id: Unique identifier for the node
            node_type: Type of the node (must be registered in NODE_REGISTRY)
            node_data: Node-specific configuration data (plain dict)
            sio: Socket.io server instance for emitting events
            sid: Session ID for sending events to specific client
            workflow_id: UUID of the workflow containing this node (for event routing)
            user_id: User ID of the workflow owner (for sandboxing/auth)
            conversation_id: Conversation ID for agent memory persistence (workflow chat only)
            organization_id: Organization ID if workflow belongs to an org (for org billing)

        Returns:
            Instantiated WorkflowNode subclass

        Raises:
            ValueError: If node_type is not registered or config is invalid
        """
        node_class = NODE_REGISTRY.get(node_type)

        if node_class is None:
            logger.error(f"[NodeFactory] Unknown node type: {node_type}")
            raise ValueError(f"Unknown node type: {node_type}. Available types: {list(NODE_REGISTRY.keys())}")

        # Parse config from dict into Pydantic model BEFORE construction
        # This allows nodes to use config in their __init__ method
        # If node has no config model or data is empty, parsed_config will be None
        parsed_config = None
        if node_data:  # Only parse if there's data
            try:
                parsed_config = node_class.parse_config(node_data)
                logger.debug(f"[NodeFactory] Parsed config for {node_class.__name__}: {type(parsed_config).__name__ if parsed_config else 'None'}")
            except ValueError as e:
                logger.error(f"[NodeFactory] Failed to parse config for {node_class.__name__}: {e}")
                raise
        else:
            logger.debug(f"[NodeFactory] No config data for {node_class.__name__}, config will be None")

        logger.debug(f"[NodeFactory] Creating {node_class.__name__} for node {node_id}")
        return node_class(node_id, node_type, node_data, parsed_config, sio, sid, workflow_id, user_id, conversation_id, organization_id, execution_id)

    @staticmethod
    def get_registered_types() -> list[str]:
        """
        Get list of all registered node types.

        Returns:
            List of registered node type identifiers
        """
        return list(NODE_REGISTRY.keys())

    @staticmethod
    def is_registered(node_type: str) -> bool:
        """
        Check if a node type is registered.

        Args:
            node_type: Node type to check

        Returns:
            True if node type is registered, False otherwise
        """
        return node_type in NODE_REGISTRY
