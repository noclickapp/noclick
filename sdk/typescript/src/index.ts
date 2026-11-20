/**
 * NoClick Platform SDK: users, sessions, connections, tools, humans, agents,
 * channels, inboxes, phone numbers, sandboxes, machines, browsers and cards;
 * databases, buckets, repos, apps and domains, each in a region; plus the activity
 * they leave (operations, events, tool calls, API requests, usage).
 *
 *     import { Connection, User, asUser } from "noclick";
 *
 *     const user = User.fromId("user_42", { createIfMissing: true });
 *     await asUser(user, async () => {
 *       const gmail = await Connection.fromName("gmail", { integration: "gmail", createIfMissing: true }).hydrate();
 *       console.log(gmail.connectUrl);
 *     });
 */

export { NoClick, configure, defaultClient, CONSOLE_BASE_URL, DEFAULT_BASE_URL } from "./client.ts";
export type { ApiKeyProvider, ClientOptions, RequestOptions, QueryValue } from "./client.ts";
export { ALL_USERS, NO_USER, asUser, currentUser } from "./scope.ts";
export type { UserFilter, UserLike, UserOption, UserRef } from "./scope.ts";
export { VERSION } from "./version.ts";
export { MAX_PAGE_SIZE } from "./object.ts";
export type { CallOptions, JsonObject, Page, PageOptions, ReadOptions } from "./object.ts";

export { User } from "./user.ts";
export type { PhoneVerification, Spending, SpendingAction, UserFields, UserListOptions } from "./user.ts";
export { Session } from "./session.ts";
export { Operation } from "./operation.ts";
export type {
  KindScopedFilters, OperationEvent, OperationFilters, OperationProgress, OperationStage, OperationStatus, OperationStep,
  OperationSummary, OperationTransition,
  PortStep, TurnStep,
} from "./operation.ts";
export { ToolCall } from "./toolCall.ts";
export type { ToolCallFilters, ToolCallSummary } from "./toolCall.ts";
export { ApiRequest } from "./apiRequest.ts";
export type { ApiRequestFilters } from "./apiRequest.ts";
export { ConnectLink, Connection, ConnectionOperations, run } from "./connection.ts";
export type {
  ConnectionAccess, ConnectionCreateOptions, ConnectionOrigin, ConnectionStatus, InWorkspace, IntegrationEvent, IntegrationInfo, IntegrationKind, IntegrationOperation, LinkOptions, LookupOption,
  LookupOptions, Plan, PlanNextStep, PlanUsage, PlanUsageState, PlanUsageSummary, PlanWindow, SendTo, Token, ToolRef, Verification,
} from "./connection.ts";
export { Toolkit } from "./toolkit.ts";
export type {
  AnthropicToolResultBlock, ApprovalRequiredInfo, HandleOptions, NeedsConnectionInfo, OnApproval, OnConnect, OpenAIToolOutput, ToolFormat, ToolResult,
} from "./toolkit.ts";
export { Human, HumanOperations, HumanRequest } from "./human.ts";
export { Approval, ApprovalPolicy } from "./approval.ts";
export type { ApprovalListOptions, ApprovalStatus, HoldKind } from "./approval.ts";
export type { Answer, HumanOptions, HumanRequestFilters, HumanRequestStatus, HumanTool, OwnerEmail, OwnerLine, OwnerReach, Via } from "./human.ts";
export { Agent, AgentConversation } from "./agent.ts";
export { TERMINAL_CLOSED_FOR_GOOD, TERMINAL_RENEW, Terminal, TerminalConnection } from "./terminal.ts";
export { AgentMove } from "./agentMove.ts";
export type { AgentMoveArrived, AgentMoveCreateOptions, AgentMoveSource, AgentMoveStatus, AgentMoveStep } from "./agentMove.ts";
export type { TerminalConnectOptions, TerminalEnd, TerminalState, TerminalStatus } from "./terminal.ts";
export type {
  AgentCommand, AgentCommandInput, AgentCommands, AgentCommandSource, HarnessRequest,
  PermissionMode, RequestDecision, AgentCreateOptions, AgentFields, AgentGrant, SandboxSize, AppTesting,
  ModelSwitching, ModelSwitchingChange, SwitchedFrom, ModelSwitchGrant, ModelSwitchResult,
  AgentHistoryOptions, AgentListOptions, AgentMovedFrom, AgentOrigin, AgentReply, AgentSkill, AgentStatus,
  AgentStep, AgentStepDiff, AgentStepKind,
  AgentToolAccess, AgentToolAction, AgentToolApp, AgentTools, Conversation, ConversationStatus, MessageDelivery,
  HarnessInfo, HarnessModel, HarnessModelPrice, HarnessModelRoute, HarnessName, JobFilters, Message, MessageSpace, MessageSubagent,
  MessageTrigger, MessageVia,
  ModelUsage,
  ReasoningLine, SpawnOptions,
  ToolRule, ToolRules, TurnLimitName, TurnLimits, WakeOptions, WakeTiming,
} from "./agent.ts";
export { Policy, Rule } from "./policy.ts";
export type { PolicyDraft, PolicyOptions, PolicyRules, PolicyVerdict, RuleInput } from "./policy.ts";
export { Brand } from "./brand.ts";
export type { BrandFields } from "./brand.ts";
export { Usage, usage } from "./usage.ts";
export type {
  AgentBudget, KeyCap, ProjectBudget, UsageGroup, UsageLimits, UsageOptions, UsagePoint, UsageSeries, UsageSeriesLine,
  UsageSeriesOptions, UserCap,
} from "./usage.ts";
export { A2AMember, Channel, Subscription } from "./channel.ts";
export type {
  ChannelAttachment, ChannelAuthor, ChannelBookmark, ChannelCreateOptions, ChannelDefinition, ChannelFile,
  ChannelLastMessage, ChannelLink, ChannelMember, ChannelMemberInput, ChannelMembership, ChannelMembershipMember,
  ChannelMessage, ChannelPin, ChannelPostAs,
  ChannelReaction, ChannelSection, ChannelSections, ChannelSectionsList, ChannelThread, SubscriptionDelivery, SubscriptionDeliveryStatus, SubscriptionSource, SubscriptionWake,
} from "./channel.ts";
export { attachments, attachmentsPage, deleteAttachment } from "./attachment.ts";
export type { Attachment, AttachmentsOptions, FileInput, UploadOptions } from "./attachment.ts";
export { Sandbox, SandboxFiles } from "./sandbox.ts";
export type { ExecOptions, ExecResult, NetworkAccess, SandboxCreateOptions, SandboxStatusFilter } from "./sandbox.ts";
export { regions } from "./region.ts";
export type { Region, RegionKind, RegionName } from "./region.ts";
export { Inbox, InboxMessage } from "./inbox.ts";
export type { InboxCreateOptions, InboxReply, InboxSenders, InboxSendOptions, InboxThread } from "./inbox.ts";
export { PhoneNumber, PhoneNumberOrder, PortRequest, TextingRegistration, TransferOut } from "./phoneNumber.ts";
export type {
  AnswerWithOptions, AvailableNumber, CallLine, ConnectableNumber, NumberCoverage, NumberDocument, NumberHolder, NumberPlace,
  NumberRequirement, NumberRequirements, PhoneNumberBuyOptions,
  PhoneCall, PhoneCallers, PhoneNumberSource, PhoneNumberType, PhoneText, PortDetails, PortInOptions,
  PortRequestNumber, StreetAddress, TextingContact, TextingRegistrationDetails, TranscriptTurn,
} from "./phoneNumber.ts";

// Each module owns its names. What isn't built yet (cards, machines, porting, texting) says so in its own doc comment.
export { Database, DatabaseOperations, QueryResult } from "./database.ts";
export type {
  BranchData, Column, DatabaseCreateOptions, DatabaseEngine, DatabaseStatus, DatabaseTool, Migration, MigrationResult,
  Migrations, SqlParams, SqlStatement, Table, UsedBy,
} from "./database.ts";
export { Bucket, BucketOperations } from "./bucket.ts";
export type {
  BucketCreateOptions, BucketData, BucketNotification, BucketObject, BucketObjectsOptions, BucketPartUrlsOptions,
  BucketPutOptions, BucketSignedUrlOptions, BucketTool, BucketUpload, BucketUploadOptions, ObjectVersion, S3Credentials,
} from "./bucket.ts";
export { Repo, RepoCheckout, RepoImport } from "./repo.ts";
export type {
  Branch, CheckoutOptions, Commit, CommitDiff, FileChange, FileSource, RepoBackup, RepoCommitOptions, RepoCreateOptions,
  RepoFile, RepoImportOptions,
} from "./repo.ts";
export { Cron } from "./cron.ts";
export type { CronOptions } from "./cron.ts";
export { Deployment, DurableObjectClass, Project, ProjectAI, ProjectSecrets, ProjectSettings, Schedule } from "./project.ts";
export type {
  AnalyticsPeriod, AnalyticsSummary, AppRequests, BadgeCorner, Bindable, Binding, BindingKind, CheckCookie, CheckPath,
  DurableObjectClasses, DurableObjectInstance,
  CheckRequest, CheckReview, ConsoleError, ContainerSettings, DeployOnPush, DeploymentCheck, DeploymentCheckOptions,
  DeploymentDatabase, DeploymentEnvironment, DeploymentFix, DeploymentRuntime, DeploymentStatus, LogLine, LogLines,
  PathCheck, PathTraffic,
  PreviewAccess, PreviewLink, PreviewResources, ProjectAnalytics, ProjectAnalyticsOptions, ProjectCreateOptions,
  ProjectLogsOptions,
  ProjectContainer, ProjectRuntime, ProjectUsage, RequestOutcomes, RouteTiming, SecretEnvironment, TrafficInterval,
} from "./project.ts";
export { ProjectEmail, ProjectPayments, ProjectSignIn } from "./appServices.ts";
export { ProjectLive } from "./live.ts";
export type {
  LiveDataCopy, LiveEdit, LiveEditApplied, LiveEditCounts, LiveEditError, LiveEditOutcome, LiveEditReload, LiveEdits,
  LiveEnd, LiveEnterLink, LiveExecOptions, LiveExecResult, LiveSession, LiveSessionState, LiveStartOptions, LiveStatus,
  LiveTimers,
} from "./live.ts";
export type {
  Broadcast, EmailBroadcastOptions, EmailCodeOptions, EmailEnableOptions, EmailSendOptions, EmailSetup,
  PaymentsEnableOptions, PaymentsSetup, SentEmail, SignInEnableOptions, SignInProvider, SignInSetup,
} from "./appServices.ts";
export { Domain, DomainDns, DomainPurchase, DomainTransfer, TransferCode } from "./domain.ts";
export type {
  DnsRecord, DomainAgreement, DomainBuyOptions, DomainContact, DomainOffer, DomainService, DomainSource, DomainStatus,
  DomainTransferOptions, TransferQuote,
} from "./domain.ts";
export { Card, CardDetails } from "./card.ts";
export type {
  CardBankTransfer, CardCreateOptions, CardDispute, CardDisputeReason, CardFunding, CardInterval,
  CardMerchantCategory, CardProgram, CardProgramStatus, CardStatus, CardTransaction, CardTransactionStatus,
  CardUpdateOptions,
} from "./card.ts";
export { Browser, BrowserLogin, BrowserProfile } from "./browser.ts";
export { BROWSER_VIEW_CLOSE, BrowserLiveView, BrowserViewConnection } from "./browserView.ts";
export type {
  BrowserViewConnectOptions, BrowserViewInput, BrowserViewOptions, BrowserViewport, BrowserViewState,
} from "./browserView.ts";
export type {
  ActResult, BrowserActOptions, BrowserActStep, BrowserContentFormat, BrowserCreateOptions, BrowserDownload,
  BrowserStatus, BrowserWaitingOn, BrowserWatchedStep, PageState, SiteLogin,
} from "./browser.ts";
export { AI } from "./ai.ts";
export type {
  AIChatMessage, AIChatOptions, AIModel, AIModelKind, AIReasoning, ChatReply, Embeddings, GeneratedImage, GeneratedVideo,
  TranscribeAudio, TranscribeOptions, Transcript, TranscriptSegment, VideoOptions,
} from "./ai.ts";
export { OnEvent, OnPlatformEvent, OnQueue, OnWebhook } from "./trigger.ts";
export type {
  AgentTrigger, AgentTriggerKind, TriggerAction, TriggerChanges, TriggerDefinition, TriggerFix, TriggerSetBy, TriggerSummary,
} from "./trigger.ts";
export { AgentMemory, AgentSandbox, AgentWorkspace, SandboxShell, ShareLink } from "./agentExtras.ts";
export type {
  AgentNow, AgentSpeed, AgentState, AgentStateRow, AgentStates, CommandResult, ConversationChanges, ConversationContext,
  ConversationRevert, ConversationSettings, ConversationUsage, ForkedFrom, LastMessage, MessageAuthor, ModelAccount,
  AgentToolServer, PlanLimit, ToolServer, ToolServers,
} from "./agentConversations.ts";
export type {
  AgentEvent, CodingAgent, CodingAgents, CodingApp, CodingCount, CodingCredential, CodingJob, CodingPause, CodingPlace,
  CodingRun, CodingState, ConversationSandbox, MemoryEntry, MemoryEntryVersion, MemoryWriter, Rehearsal, SandboxFilesOptions,
  SandboxFilesPage, SandboxPlace, WorkspaceFile,
} from "./agentExtras.ts";
export { Agents, Before, Every, Job, Platform, Wakeup } from "./coordination.ts";
export type {
  AgentsTool, JobUpdate, JobUpdateKind, PlatformGroup, UpdateSpec, WakeupSource, WakeupStatus,
} from "./coordination.ts";
export { Workspace, WorkspaceInvite, WorkspaceResource } from "./workspace.ts";
export type {
  InvitePreview, MyWorkspace, WorkspaceCreateOptions, WorkspaceMember, WorkspaceMemberInput, WorkspaceResourceKind,
  SpaceQuestion, WorkspaceRole, WorkspaceSummary, WorkspaceSummaryKind,
} from "./workspace.ts";
export { McpServer } from "./mcpServer.ts";
export type { McpClient, McpServerTools } from "./mcpServer.ts";
export { Event, Webhook } from "./webhook.ts";
export { WatchRefused, watch, watchToken } from "./watch.ts";
export type {
  WatchChange, WatchMessage, WatchOptions, WatchReady, WatchReset, WatchStatus, WatchToken, WatchTokenOptions,
  WatchTyping, WatchedObject,
} from "./watch.ts";
export type {
  EventListOptions, EventType, WebhookChanges, WebhookCreateOptions, WebhookDelivery, WebhookDeliveryStatus,
  WebhookHeaders, WebhookStatus,
} from "./webhook.ts";
export { EditBatch, Step, Workflow, WorkflowBuild, WorkflowGraph } from "./workflow.ts";
export type {
  AddNoteOptions, AddStepOptions, BuildQuestion, EditOptions, GraphEdge, Position, PublishOptions, RunStep,
  StepConnection, StepRef, StepTrigger, StepUpdate, WorkflowBuildResult, WorkflowEdge, WorkflowEdit,
  WorkflowEndpoint, WorkflowReadiness, WorkflowRun, WorkflowRunOptions, WorkflowRunStatus, WorkflowStep,
  WorkflowUpdate, WorkflowUrl, WorkflowVersion,
} from "./workflow.ts";
export { WorkflowFile, WorkflowTable } from "./workflowResources.ts";
export type { KeptBy, RowsPage, TableRow, WorkflowResourceListOptions } from "./workflowResources.ts";
export type { ExportBundle, ExportItem } from "./export.ts";
export { Volume } from "./volume.ts";
export type { VolumeData, VolumeEntry, VolumeListdirOptions, VolumeMount, VolumeRef } from "./volume.ts";
export { Memory, MemoryLink } from "./memory.ts";
export type { MemoryAttachment, MemoryRef } from "./memory.ts";
export { Skill, SkillLink } from "./skill.ts";
export type { SkillAttachment, SkillAuthor, SkillFile, SkillFileInfo, SkillFiles, SkillRef, SkillVersion } from "./skill.ts";
export { compute } from "./compute.ts";
export type { ComputeItem, ComputeRun } from "./compute.ts";
export { Estimate, estimate } from "./estimate.ts";
export type {
  EstimateItem, EstimateKind, EstimateLine, EstimatePrice, EstimateRequestItem, EstimateUsageField,
} from "./estimate.ts";
export { Dict } from "./dict.ts";
export type { DictChange, DictItem, DictListOptions, DictWriteOptions } from "./dict.ts";
export { Queue, QueueMessage } from "./queue.ts";
export type { QueueCreateOptions, QueueDepth, QueueMessageStatus } from "./queue.ts";
export { Secret } from "./secret.ts";
export type { SecretCreateOptions, SecretRef } from "./secret.ts";
export { TrashItem } from "./trash.ts";
export type { TrashKind, TrashListOptions } from "./trash.ts";
export type { Version } from "./versions.ts";
export { Machine, MachineFiles } from "./machine.ts";
export type {
  MachineAddOwnOptions, MachineAgentState, MachineCreateOptions, MachineFileEntry, MachineHealth, MachineKind, MachinePairing, MachinePort, MachineShell, MachineRefusal, MachineSize, MachineSizeName, MachineSizeRegion, MachineHost, MachineHostName,
  MachineStatus,
} from "./machine.ts";
export { feedback } from "./feedback.ts";
export type { FeedbackKind } from "./feedback.ts";

export {
  NoClickError,
  InvalidRequest,
  Unauthenticated,
  PaymentRequired,
  PlanRequired,
  PriceExceeded,
  ApprovalRequired,
  SpendCapExceeded,
  SpendingPaused,
  PermissionDenied,
  PolicyDenied,
  NotFound,
  Conflict,
  NotAvailable,
  ActionRequired,
  AnswerRequired,
  Expired,
  OperationExpired,
  NeedsConnection,
  CredentialDisconnected,
  QuotaExceeded,
  PlanLimitReached,
  RateLimited,
  UpstreamError,
  RequestTimeout,
  ServerError,
  APIConnectionError,
  OperationFailed,
  OperationCanceled,
  OperationTimeout,
  WebhookSignatureError,
} from "./errors.ts";
export type { ErrorInit, Offer } from "./errors.ts";
