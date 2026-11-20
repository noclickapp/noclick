"""NoClick Platform SDK: users, sessions, connections, tools, humans,
agents and the agents they coordinate, policy, channels and workspaces,
inboxes, phone numbers, sandboxes, machines, browsers and cards; databases,
buckets, repos, apps and domains, each in a region; plus the activity they
leave (operations, events, tool calls, API requests, usage).

    import noclick

    user = noclick.User.from_id("user_42", create_if_missing=True)
    with noclick.as_user(user):
        gmail = noclick.Connection.from_name("gmail", integration="gmail", create_if_missing=True)
        print(gmail.connect_url)

Every method blocks by default; ``await obj.method.aio(...)`` is the async form.
"""

from ._client import CONSOLE_BASE_URL, DEFAULT_BASE_URL, Client, configure, default_client
from ._object import MAX_PAGE_SIZE, Page
from ._scope import ALL_USERS, NO_USER, as_user, current_user
from ._usage import (
    AgentBudget, KeyCap, ProjectBudget, Usage, UsageGroup, UsageLimits, UsagePoint, UsageSeries, UsageSeriesLine, UserCap,
    usage,
)
from ._version import __version__
from .agent_conversations import (
    AgentConversation, AgentStateRow, CommandResult, ConversationContext, ConversationRevert, ConversationSettings,
    AgentToolServer, ConversationUsage, ToolServer, ToolServers,
)
from .agent import (
    Agent, AgentCommand, AgentCommands, AgentGrant, HarnessRequest, AgentReply, AgentStep, AgentStepDiff, Conversation, HarnessInfo,
    AgentToolAccess, AgentToolAction, AgentToolApp, HarnessModel, Message, ModelSwitchGrant, ModelSwitching,
    ModelUsage,
)
from .agent_extras import (
    AgentEvent, AgentMemory, AgentSandbox, AgentWorkspace, CodingAgent, CodingAgents, CodingApp, CodingCount,
    CodingCredential, CodingJob, CodingPause, CodingRun, ConversationSandbox, MemoryEntry, MemoryEntryVersion,
    MemoryWriter, Rehearsal, SandboxFilesPage, SandboxShell, ShareLink, WorkspaceFile,
)
from .ai import (
    AI, AIModel, AIReasoning, ChatReply, Embeddings, GeneratedImage, GeneratedVideo, Transcript, TranscriptSegment,
)
from .app_services import (
    Broadcast, EmailSetup, PaymentsSetup, ProjectEmail, ProjectPayments, ProjectSignIn, SentEmail, SignInSetup,
)
from .api_request import ApiRequest
from .approval import Approval, ApprovalPolicy, HoldKind
from .brand import Brand
from .browser import (
    ActResult, Browser, BrowserLiveView, BrowserLogin, BrowserProfile, BrowserWaitingOn, BrowserWatchedStep, PageState,
    SiteLogin,
)
from .bucket import Bucket, BucketObject, BucketOperations, BucketUpload, ObjectVersion, S3Credentials
from .card import (
    Card, CardBankTransfer, CardDetails, CardDispute, CardFunding, CardMerchantCategory, CardProgram, CardTransaction,
)
from .channel import (
    A2AMember, Channel, ChannelAttachment, ChannelAuthor, ChannelBookmark, ChannelFile, ChannelLink, ChannelMember,
    ChannelMembership, ChannelMessage, ChannelPin, ChannelReaction, ChannelSection, ChannelSections, ChannelThread,
    Subscription, SubscriptionDelivery,
)
from .connection import (
    Connection, ConnectionOperations, ConnectLink, IntegrationEvent, IntegrationInfo, IntegrationOperation, LookupOption,
    LookupOptions, PlanNextStep, Plan, PlanUsage, PlanUsageSummary, PlanWindow, Token, Verification, run,
)
from ._attachment import Attachment, attachments, attachments_page, delete_attachment
from ._feedback import feedback
from .coordination import Agents, Before, Every, Job, JobUpdate, Platform, Wakeup
from .terminal import Terminal
from .agent_move import AgentMove
from .cron import Cron
from .database import Column, Database, DatabaseOperations, Migration, MigrationResult, QueryResult, Table
from .dicts import Dict, DictChange, DictItem
from .domain import (
    DnsRecord, Domain, DomainAgreement, DomainContact, DomainDns, DomainOffer, DomainPurchase, DomainTransfer,
    TransferCode, TransferQuote,
)
from .exceptions import (
    ActionRequired,
    AnswerRequired,
    APIConnectionError,
    ApprovalRequired,
    Conflict,
    CredentialDisconnected,
    Error,
    Expired,
    InvalidRequest,
    NeedsConnection,
    NotAvailable,
    NotFound,
    Offer,
    OperationCanceled,
    OperationExpired,
    OperationFailed,
    OperationTimeout,
    PaymentRequired,
    PermissionDenied,
    PlanRequired,
    PolicyDenied,
    PriceExceeded,
    PlanLimitReached,
    QuotaExceeded,
    RateLimited,
    RequestTimeout,
    ServerError,
    SpendCapExceeded,
    SpendingPaused,
    Unauthenticated,
    UpstreamError,
    WebhookSignatureError,
)
from .export import ExportBundle, ExportItem
from .human import Answer, Human, HumanOperations, HumanRequest, OwnerEmail, OwnerLine, OwnerReach
from .inbox import Inbox, InboxMessage, InboxReply, InboxThread
from .live import (
    LiveDataCopy, LiveEdit, LiveEditCounts, LiveEdits, LiveEnd, LiveEnterLink, LiveExecResult, LiveSession, LiveStatus,
    ProjectLive,
)
from .machine import (
    Machine, MachineFileEntry, MachineFiles, MachineHealth, MachineHost, MachinePairing, MachinePort, MachineRefusal,
    MachineShell, MachineSize, MachineSizeRegion,
)
from .mcp_server import McpClient, McpServer
from .operation import Operation, OperationEvent, OperationSummary, OperationTransition
from .phone_number import (
    AvailableNumber, ConnectableNumber, NumberCoverage, NumberDocument, NumberHolder, NumberPlace, PhoneCall, PhoneNumber,
    PhoneNumberOrder, PhoneText, PortRequest, TextingRegistration, TransferOut,
)
from .policy import Policy, PolicyVerdict, Rule
from .project import (
    AnalyticsSummary, AppRequests, Binding, CheckReview, Deployment, DeploymentCheck, LogLine, LogLines, PathCheck,
    PathTraffic, PreviewLink, Project, ProjectAI, ProjectAnalytics, ProjectContainer, ProjectSecrets, ProjectSettings,
    ProjectUsage, RequestOutcomes, RouteTiming, Schedule, TrafficInterval, DurableObjectClass, DurableObjectClasses,
    DurableObjectInstance,
)
from .queues import Queue, QueueDepth, QueueMessage
from .region import Region, regions
from .repo import Branch, Commit, CommitDiff, FileChange, Repo, RepoBackup, RepoCheckout, RepoFile, RepoImport
from .sandbox import ExecResult, Sandbox, SandboxFiles
from .secret import Secret
from .session import Session
from .tool_call import ToolCall, ToolCallSummary
from .trash import TrashItem
from .toolkit import Toolkit, ToolResult
from .trigger import AgentTrigger, OnEvent, OnPlatformEvent, OnQueue, OnWebhook
from .user import PhoneVerification, Spending, User
from .versions import Version
from .volume import Volume, VolumeEntry
from .memory import Memory, MemoryLink
from .skill import Skill, SkillAttachment, SkillAuthor, SkillFile, SkillFileInfo, SkillLink, SkillVersion
from .compute import ComputeItem, ComputeRun, compute
from .estimate import (
    Estimate, EstimateItem, EstimateKind, EstimateLine, EstimatePrice, EstimateUsageField, estimate,
)
from .webhook import Event, EventType, Webhook, WebhookDelivery
from ._watch import (
    WatchChange, WatchMessage, WatchReady, WatchRefused, WatchReset, WatchToken, WatchTyping, watch, watch_token,
)
from .workspace import MyWorkspace, SpaceQuestion, Workspace, WorkspaceInvite, WorkspaceMember, WorkspaceResource
from .workflow import (
    BuildQuestion, EditBatch, RunStep, Step, Workflow, WorkflowBuild, WorkflowBuildResult, WorkflowEdit, WorkflowEndpoint,
    WorkflowGraph, WorkflowRun, WorkflowStep, WorkflowVersion,
)
from .workflow_resources import RowsPage, TableRow, WorkflowFile, WorkflowTable

__all__ = [
    "__version__",
    "Client", "configure", "default_client", "DEFAULT_BASE_URL", "CONSOLE_BASE_URL",
    "as_user", "current_user", "ALL_USERS", "NO_USER",
    "Page", "MAX_PAGE_SIZE",
    "User", "PhoneVerification", "Spending", "Session",
    "Operation", "OperationEvent", "OperationSummary", "OperationTransition",
    "ToolCall", "ToolCallSummary", "ApiRequest",
    "Connection", "run", "ConnectionOperations", "ConnectLink", "Verification", "Token", "LookupOption", "LookupOptions",
    "Plan", "PlanWindow", "PlanUsage", "PlanUsageSummary", "PlanNextStep",
    "IntegrationInfo", "IntegrationOperation", "IntegrationEvent",
    "Toolkit", "ToolResult",
    "Human", "HumanRequest", "HumanOperations", "Answer", "OwnerEmail", "OwnerLine", "OwnerReach", "Approval",
    "ApprovalPolicy", "HoldKind",
    "Agent", "AgentConversation", "AgentStateRow", "CommandResult", "ConversationContext", "ConversationRevert",
    "AgentToolServer", "ConversationUsage", "ToolServer", "ToolServers", "AgentCommand", "AgentCommands", "AgentGrant", "ConversationSettings", "HarnessRequest", "AgentReply", "AgentStep", "AgentStepDiff", "Conversation",
    "Message", "HarnessInfo",
    "HarnessModel", "ModelUsage", "ModelSwitching", "ModelSwitchGrant", "AgentToolAccess", "AgentToolApp",
    "AgentToolAction",
    "Cron", "OnWebhook", "OnEvent", "OnPlatformEvent", "OnQueue", "AgentTrigger",
    "AgentMemory", "MemoryEntry", "MemoryEntryVersion", "MemoryWriter", "Memory", "MemoryLink", "Skill", "SkillAttachment", "SkillAuthor",
    "SkillFile", "SkillFileInfo", "SkillLink", "SkillVersion", "compute", "ComputeItem", "ComputeRun", "AgentWorkspace", "WorkspaceFile", "ShareLink",
    "AgentSandbox", "ConversationSandbox", "SandboxFilesPage", "SandboxShell", "CodingAgents", "CodingAgent", "CodingApp",
    "CodingCount", "CodingCredential", "CodingJob", "CodingPause", "CodingRun",
    "AgentEvent", "Rehearsal",
    "Wakeup", "Job", "JobUpdate", "Before", "Every", "Agents", "Platform", "Attachment", "Terminal",
    "AgentMove",
    "McpServer", "McpClient", "AI", "ChatReply", "Embeddings", "GeneratedImage", "GeneratedVideo", "Transcript",
    "TranscriptSegment", "AIModel", "AIReasoning", "feedback", "attachments", "attachments_page", "delete_attachment",
    "Channel", "ChannelMember", "ChannelMembership", "ChannelMessage", "ChannelAuthor", "ChannelAttachment", "ChannelReaction",
    "ChannelThread", "ChannelSection", "ChannelSections", "ChannelPin", "ChannelBookmark", "ChannelFile", "ChannelLink",
    "A2AMember", "Subscription", "SubscriptionDelivery",
    "Workspace", "WorkspaceMember", "WorkspaceInvite", "MyWorkspace", "WorkspaceResource", "SpaceQuestion",
    "Inbox", "InboxMessage", "InboxReply", "InboxThread",
    "PhoneNumber", "AvailableNumber", "PhoneCall", "ConnectableNumber", "PortRequest", "TextingRegistration",
    "PhoneText", "TransferOut", "NumberHolder", "NumberCoverage", "NumberPlace", "NumberDocument", "PhoneNumberOrder",
    "Sandbox", "SandboxFiles", "ExecResult", "Machine", "MachineSize", "MachineSizeRegion", "MachineHost", "MachinePort", "MachinePairing", "MachineRefusal", "MachineFiles", "MachineFileEntry", "MachineHealth", "MachineShell",
    "regions", "Region",
    "Browser", "BrowserLiveView", "BrowserProfile", "BrowserLogin", "PageState", "ActResult", "SiteLogin",
    "BrowserWatchedStep",
    "BrowserWaitingOn",
    "Card", "CardTransaction", "CardDetails", "CardFunding", "CardBankTransfer", "CardDispute", "CardProgram",
    "CardMerchantCategory",
    "Project", "Deployment", "Schedule", "DurableObjectClass", "DurableObjectClasses", "DurableObjectInstance",
    "ProjectSecrets", "ProjectSettings", "ProjectAI", "Binding", "LogLine",
    "LogLines", "ProjectUsage", "DeploymentCheck", "PathCheck", "CheckReview", "RequestOutcomes", "RouteTiming",
    "ProjectAnalytics", "TrafficInterval", "PathTraffic", "AnalyticsSummary", "AppRequests", "PreviewLink",
    "ProjectContainer", "ProjectEmail", "EmailSetup", "SentEmail", "Broadcast", "ProjectPayments", "PaymentsSetup", "ProjectSignIn", "SignInSetup",
    "ProjectLive", "LiveStatus", "LiveSession", "LiveEditCounts", "LiveDataCopy", "LiveEdit", "LiveEdits",
    "LiveExecResult", "LiveEnterLink", "LiveEnd",
    "Repo", "Commit", "CommitDiff", "FileChange", "Branch", "RepoBackup", "RepoFile", "RepoCheckout", "RepoImport",
    "Database", "DatabaseOperations", "QueryResult", "Migration", "MigrationResult", "Table", "Column",
    "Bucket", "BucketObject", "ObjectVersion", "BucketOperations", "BucketUpload", "S3Credentials",
    "Volume", "VolumeEntry", "Dict", "DictItem", "DictChange", "Queue", "QueueMessage", "QueueDepth", "Secret",
    "Version", "TrashItem",
    "Domain", "DomainOffer", "DomainContact", "DomainPurchase", "DomainTransfer", "DnsRecord", "DomainDns", "TransferCode",
    "TransferQuote", "DomainAgreement",
    "Webhook", "WebhookDelivery", "Event", "EventType",
    "watch", "watch_token", "WatchMessage", "WatchReady", "WatchChange", "WatchTyping", "WatchReset", "WatchToken",
    "WatchRefused",
    "Workflow", "WorkflowRun", "RunStep", "WorkflowEndpoint", "WorkflowBuild", "WorkflowBuildResult", "WorkflowStep",
    "WorkflowGraph", "Step", "EditBatch", "WorkflowEdit", "WorkflowVersion", "WorkflowFile", "WorkflowTable", "TableRow",
    "RowsPage",
    "BuildQuestion", "ExportBundle", "ExportItem",
    "Policy", "PolicyVerdict", "Rule", "Brand", "usage", "Usage", "UsageGroup",
    "estimate", "Estimate", "EstimateItem", "EstimateLine", "EstimateKind", "EstimateUsageField", "EstimatePrice",
    "UsageSeries", "UsageSeriesLine", "UsagePoint", "UsageLimits", "KeyCap", "UserCap", "AgentBudget", "ProjectBudget",
    "Error", "Offer", "InvalidRequest", "Unauthenticated", "PaymentRequired", "PlanRequired",
    "PriceExceeded", "ApprovalRequired", "SpendCapExceeded", "SpendingPaused", "PermissionDenied", "PolicyDenied", "NotFound",
    "Conflict", "NotAvailable", "ActionRequired", "AnswerRequired", "NeedsConnection", "CredentialDisconnected",
    "QuotaExceeded", "PlanLimitReached", "RateLimited", "UpstreamError", "RequestTimeout", "ServerError", "APIConnectionError",
    "OperationFailed",
    "OperationCanceled", "Expired", "OperationExpired", "OperationTimeout", "WebhookSignatureError",
]
