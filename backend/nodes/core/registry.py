"""
Node registry for dynamically loading workflow node classes.

Provides a centralized registry that maps node types to their implementation classes
and handles instantiation of nodes based on type.
"""

import logging
from pathlib import Path
from collections.abc import Mapping, MutableMapping
from typing import Dict, Optional, Tuple, Type, Any, Union
from nodes.core.base import Retirement, WorkflowNode
from nodes.core.discovery import Declaration, declare_nodes, merge_node_entries

logger = logging.getLogger(__name__)


# Registry mapping node types to their implementation classes
# Node types registered by hand: type -> (module, class). Each imports at its type's first
# lookup, as a self-registered integration does.
_NODE_REGISTRY_ENTRIES: Dict[str, Tuple[str, str]] = {
    # Trigger nodes (entry points for workflows)
    'trigger-run': ('nodes.run_trigger_node', 'RunTriggerNode'),
    'trigger-webhook': ('nodes.webhook_trigger_node', 'WebhookTriggerNode'),
    'trigger-email': ('nodes.inbound_email_trigger_node', 'InboundEmailTriggerNode'),
    'trigger-cron': ('nodes.cron_trigger_node', 'CronTriggerNode'),

    # Automation nodes
    'automation-telegram': ('nodes.telegram_node', 'TelegramNode'),
    'automation-phone': ('nodes.phone_node', 'PhoneNode'),
    'automation-http-request': ('nodes.http_request_node', 'HttpRequestNode'),
    'automation-linear': ('nodes.linear_node', 'LinearNode'),
    'automation-github-rest': ('nodes.github_rest_node', 'GithubRestNode'),
    'automation-stripe': ('nodes.stripe_node', 'StripeNode'),
    'automation-discord': ('nodes.discord_node', 'DiscordNode'),
    'automation-hubspot': ('nodes.hubspot_node', 'HubSpotNode'),
    'automation-instagram': ('nodes.instagram_node', 'InstagramNode'),
    'automation-facebook': ('nodes.facebook_node', 'FacebookNode'),
    'automation-meta': ('nodes.meta_node', 'MetaNode'),
    'automation-instantly': ('nodes.instantly_node', 'InstantlyNode'),
    'automation-jira': ('nodes.jira_node', 'JiraNode'),
    'automation-notion': ('nodes.notion_node', 'NotionNode'),
    'automation-redis': ('nodes.redis_node', 'RedisNode'),
    'automation-salesforce': ('nodes.salesforce_node', 'SalesforceNode'),
    'automation-shopify': ('nodes.shopify_node', 'ShopifyNode'),
    'automation-slack': ('nodes.slack_node', 'SlackNode'),
    'automation-pipedrive': ('nodes.pipedrive_node', 'PipedriveNode'),
    'automation-resend': ('nodes.resend_node', 'ResendNode'),
    'automation-threads': ('nodes.threads_node', 'ThreadsNode'),
    'automation-phantombuster': ('nodes.phantombuster_node', 'PhantomBusterNode'),
    'automation-cal-com': ('nodes.cal_com_node', 'CalComNode'),
    'automation-calendly': ('nodes.calendly_node', 'CalendlyNode'),
    'automation-honeycomb': ('nodes.honeycomb_node', 'HoneycombNode'),
    'automation-sentry': ('nodes.sentry_node', 'SentryNode'),
    'automation-perplexity': ('nodes.perplexity_node', 'PerplexityNode'),
    'automation-posthog': ('nodes.posthog_node', 'PostHogNode'),
    'automation-atlas-admin': ('nodes.atlas_admin_node', 'AtlasAdminNode'),
    'automation-mailgun': ('nodes.mailgun_node', 'MailgunNode'),
    'automation-gitlab': ('nodes.gitlab_node', 'GitLabNode'),
    'automation-box': ('nodes.box_node', 'BoxNode'),
    'automation-clickup': ('nodes.clickup_node', 'ClickUpNode'),
    'automation-devin': ('nodes.devin_node', 'DevinNode'),
    'automation-asana': ('nodes.asana_node', 'AsanaNode'),
    'automation-firestore': ('nodes.firestore_node', 'FirestoreNode'),
    'automation-google-cloud-storage': ('nodes.google_cloud_storage_node', 'GoogleCloudStorageNode'),
    'automation-monday': ('nodes.monday_node', 'MondayNode'),
    'automation-parallel': ('nodes.parallel_node', 'ParallelNode'),
    'automation-datadog': ('nodes.datadog_node', 'DatadogNode'),
    'automation-loops': ('nodes.loops_node', 'LoopsNode'),
    'automation-exa': ('nodes.exa_node', 'ExaNode'),
    'automation-reducto': ('nodes.reducto_node', 'ReductoNode'),
    'automation-fal': ('nodes.fal_node', 'FalNode'),
    'automation-brandfetch': ('nodes.brandfetch_node', 'BrandfetchNode'),
    'automation-findymail': ('nodes.findymail_node', 'FindymailNode'),
    'automation-beehiiv': ('nodes.beehiiv_node', 'BeehiivNode'),
    'automation-hex': ('nodes.hex_node', 'HexNode'),
    'automation-clickhouse': ('nodes.clickhouse_node', 'ClickHouseNode'),
    'automation-extend': ('nodes.extend_node', 'ExtendNode'),
    'automation-fellow': ('nodes.fellow_node', 'FellowNode'),
    'automation-fathom': ('nodes.fathom_node', 'FathomNode'),
    'automation-sigma': ('nodes.sigma_node', 'SigmaNode'),
    'automation-trello': ('nodes.trello_node', 'TrelloNode'),
    'automation-firecrawl': ('nodes.firecrawl_node', 'FirecrawlNode'),
    'automation-attio': ('nodes.attio_node', 'AttioNode'),
    'automation-intercom': ('nodes.intercom_node', 'IntercomNode'),
    'automation-zendesk': ('nodes.zendesk_node', 'ZendeskNode'),
    'automation-confluence': ('nodes.confluence_node', 'ConfluenceNode'),
    'automation-pagerduty': ('nodes.pagerduty_node', 'PagerDutyNode'),
    'automation-google-meet': ('nodes.google_meet_node', 'GoogleMeetNode'),
    'automation-expensify': ('nodes.expensify_node', 'ExpensifyNode'),
    'automation-freshsales': ('nodes.freshsales_node', 'FreshsalesNode'),
    'automation-launchdarkly': ('nodes.launchdarkly_node', 'LaunchDarklyNode'),
    'automation-appsheet': ('nodes.appsheet_node', 'AppSheetNode'),
    'automation-tableau': ('nodes.tableau_node', 'TableauNode'),
    'automation-webflow': ('nodes.webflow_node', 'WebflowNode'),
    'automation-google-translate': ('nodes.google_translate_node', 'GoogleTranslateNode'),
    'automation-bigquery': ('nodes.bigquery_node', 'BigQueryNode'),
    'automation-snowflake': ('nodes.snowflake_node', 'SnowflakeNode'),
    'automation-databricks': ('nodes.databricks_node', 'DatabricksNode'),
    'automation-microsoft-teams': ('nodes.microsoft_teams_node', 'MicrosoftTeamsNode'),
    'automation-gohighlevel': ('nodes.gohighlevel_node', 'GoHighLevelNode'),
    'automation-quickbooks': ('nodes.quickbooks_node', 'QuickBooksNode'),
    'automation-zoom': ('nodes.zoom_node', 'ZoomNode'),
    'automation-klaviyo': ('nodes.klaviyo_node', 'KlaviyoNode'),
    'automation-onelake': ('nodes.onelake_node', 'OneLakeNode'),
    'automation-bamboohr': ('nodes.bamboohr_node', 'BambooHRNode'),
    'automation-dv360': ('nodes.dv360_node', 'DV360Node'),
    'automation-send-email': ('nodes.send_email_node', 'SendEmailNode'),
    'automation-table': ('nodes.table_node', 'TableNode'),
    'automation-typeform': ('nodes.typeform_node', 'TypeformNode'),
    'automation-twilio': ('nodes.twilio_node', 'TwilioNode'),
    'automation-cloudflare': ('nodes.cloudflare_node', 'CloudflareNode'),
    'automation-whatsapp': ('nodes.whatsapp_node', 'WhatsAppNode'),

    # Google integrations
    'automation-google-sheets': ('nodes.google_sheets_node', 'GoogleSheetsNode'),
    'automation-google-drive': ('nodes.google_drive_node', 'GoogleDriveNode'),
    'automation-gmail': ('nodes.gmail_node', 'GmailNode'),
    'automation-google-calendar': ('nodes.google_calendar_node', 'GoogleCalendarNode'),
    'automation-google-forms': ('nodes.google_forms_node', 'GoogleFormsNode'),

    # Microsoft integrations
    'automation-outlook': ('nodes.outlook_mail_node', 'OutlookMailNode'),

    # AI Agent nodes
    'agent': ('nodes.agent_node', 'AgentNode'),
    'tool': ('nodes.tool_node', 'ToolNode'),
    'mcp-server': ('nodes.mcp_server_node', 'MCPServerNode'),
    'noclick': ('nodes.noclick_node', 'NoClickNode'),
    'alarm': ('nodes.alarm_node', 'AlarmNode'),
    'filesystem': ('nodes.filesystem_node', 'FilesystemNode'),

    # Control flow nodes
    'iteration': ('nodes.iteration_node', 'IterationNode'),
    'delay': ('nodes.delay_node', 'DelayNode'),
    'filter': ('nodes.filter_node', 'FilterNode'),
    'split-out': ('nodes.split_out_node', 'SplitOutNode'),
    'conditional': ('nodes.conditional_node', 'ConditionalNode'),
    'switch': ('nodes.switch_node', 'SwitchNode'),
    'merge': ('nodes.merge_node', 'MergeNode'),
    'approval': ('nodes.approval_node', 'ApprovalNode'),
    'log': ('nodes.log_node', 'LogNode'),
    'automation-submit-external-form': ('nodes.submit_external_form_node', 'SubmitExternalFormNode'),

    # Compute nodes
    'automation-serverless-function': ('nodes.serverless_function_node', 'ServerlessFunctionNode'),

    # State management nodes
    'state-manager': ('nodes.state_manager_node', 'StateManagerNode'),

    # Setup node (entry point for guided template onboarding)

    # On-error node (runs when workflow execution encounters an error)
    'on-error': ('nodes.on_error_node', 'OnErrorNode'),

    # Set variable node (stores values as global variables)
    'set-variable': ('nodes.set_variable_node', 'SetVariableNode'),

    # Interface nodes (UI components for the workflow interface builder)
    'interface-form': ('nodes.interface.form_node', 'FormInterfaceNode'),
    'interface-file': ('nodes.interface.file_node', 'FileInterfaceNode'),
    'interface-dataframe': ('nodes.interface.dataframe_node', 'DataframeInterfaceNode'),
    'interface-html-react': ('nodes.interface.html_react_node', 'HtmlReactInterfaceNode'),
    'interface-file-upload': ('nodes.interface.file_upload_node', 'FileUploadInterfaceNode'),

    # Test nodes (for testing only)
    'test-dummy': ('nodes.dummy_node', 'DummyNode'),
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


class _NodeRegistry(MutableMapping[str, Type[WorkflowNode]]):
    """Node type -> class, resolving LEGACY_NODE_TYPE_ALIASES on lookup but not on iteration.

    A self-registered integration is held as its ``Declaration`` until its type is
    first looked up, then as its class. Listing the types imports nothing;
    ``values()``/``items()`` import every integration, seconds of CPU and most of
    a process's memory, so a request path shouldn't walk them.
    """

    def __init__(self, entries: Mapping[str, Union[Type[WorkflowNode], Declaration]]):
        self._entries: Dict[str, Union[Type[WorkflowNode], Declaration]] = dict(entries)

    def _key(self, key):
        if key in self._entries:
            return key
        alias = LEGACY_NODE_TYPE_ALIASES.get(key)
        if alias is not None and alias in self._entries:
            return alias
        raise KeyError(key)

    def __getitem__(self, key):
        key = self._key(key)
        entry = self._entries[key]
        if isinstance(entry, Declaration):
            entry = self._entries[key] = entry.load()
        return entry

    def __contains__(self, key):
        try:
            self._key(key)
        except (KeyError, TypeError):
            return False
        return True

    def __iter__(self):
        return iter(self._entries)

    def __len__(self):
        return len(self._entries)

    def __setitem__(self, key, value):
        self._entries[key] = value

    def __delitem__(self, key):
        del self._entries[key]

    def type_of(self, cls: type) -> Optional[str]:
        """The type ``cls`` is registered under, found without importing any other integration."""
        for key, entry in self._entries.items():
            if entry is cls or (
                isinstance(entry, Declaration)
                and (entry.module, entry.class_name) == (cls.__module__, cls.__name__)
                and self[key] is cls
            ):
                return key
        return None


from nodes.core.oauth_registry import oauth_providers  # noqa: E402

# OAuth provider declarations still fail startup; that each node's credential
# names its provider is a fact of the code, checked by the suite
# (test_oauth_credentials_belong_to_their_provider), not by every process.
oauth_providers()

DISCOVERED_NODE_ENTRIES = declare_nodes(Path(__file__).resolve().parents[1])
NODE_REGISTRY: _NodeRegistry = _NodeRegistry(
    merge_node_entries(
        {node_type: Declaration(node_type, module, name, self_declared=False)
         for node_type, (module, name) in _NODE_REGISTRY_ENTRIES.items()},
        DISCOVERED_NODE_ENTRIES,
    )
)


def is_connectionless(node_type: str) -> bool:
    """A node that talks over the SDK, never edges (WorkflowNode.connectionless)."""
    cls = NODE_REGISTRY.get(node_type)
    return bool(getattr(cls, 'connectionless', False))


def retirement_of(node_type: Optional[str]) -> Optional[Retirement]:
    """Why the type's service is gone, or None while it's live (or unknown)."""
    node_class = NODE_REGISTRY.get(node_type) if node_type else None
    return node_class.retired if node_class else None


def is_listed(node_type: Optional[str]) -> bool:
    """Whether a listing (a catalog, a search, a builder's or MCP's node list)
    offers the type for new work. A retired type stays registered, so a saved
    node of it still loads, renders and runs."""
    return retirement_of(node_type) is None


def validate_edge(source_type: str, target_type: str) -> str | None:
    """Return an error string if this edge is invalid, or None if OK."""
    if is_connectionless(source_type):
        return f"Cannot add edge from {source_type}: uses SDK for communication, not edges"
    if is_connectionless(target_type):
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
