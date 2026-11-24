// GENERATED from NoClick's API: do not edit. NoClick's agent tools by their titles, every /v1 operation's
// summary, method and risk class (as api_describe answers them), and the apps an agent calls operations of.
export const PLATFORM_TOOL_TITLES: Record<string, string> = {
    "search": "Search NoClick",
    "fetch": "Fetch a doc or object",
    "api_describe": "Describe API operations",
    "api_call": "Call an API operation",
    "quote": "Price a purchase",
    "buy": "Buy a quoted item",
    "delete": "Delete, cancel or revoke"
};

/** name → [summary, method, risk] */
export const OPERATIONS: Record<string, [string, string, string]> = {
    "account_funds_create": ["Add Funds", "POST", "write"],
    "account_payment_links_create": ["Create Payment Link", "POST", "write"],
    "agent_signups_current": ["Get Current", "GET", "read"],
    "agent_signups_current_claim_link": ["New Claim Link", "POST", "write"],
    "agents_a2a": ["A2A Rpc", "POST", "outbound"],
    "agents_a2a_card": ["A2A Card", "GET", "read"],
    "agents_ask": ["Ask Agent", "POST", "outbound"],
    "agents_attachments_create": ["Upload Attachment", "POST", "write"],
    "agents_children": ["Create Child Agent", "POST", "outbound"],
    "agents_children_create": ["Create Child Agent", "POST", "outbound"],
    "agents_coding": ["List Coding Agents", "GET", "read"],
    "agents_conversations_activity": ["Conversation Activity", "GET", "read"],
    "agents_conversations_commands_list": ["List Commands", "GET", "read"],
    "agents_conversations_context": ["Conversation Context", "GET", "read"],
    "agents_conversations_create": ["Start Conversation", "POST", "write"],
    "agents_conversations_fork": ["Fork Conversation", "POST", "write"],
    "agents_conversations_get": ["Read Conversation", "GET", "read"],
    "agents_conversations_hand_back": ["Hand Back", "POST", "write"],
    "agents_conversations_list": ["List Conversations", "GET", "read"],
    "agents_conversations_notes_create": ["Add Note", "POST", "write"],
    "agents_conversations_requests_list": ["List Requests", "GET", "read"],
    "agents_conversations_resume": ["Resume Conversation", "POST", "write"],
    "agents_conversations_revert": ["Revert Conversation", "POST", "write"],
    "agents_conversations_sandbox": ["Get Sandbox", "GET", "read"],
    "agents_conversations_settings_list": ["Read Conversation Settings", "GET", "read"],
    "agents_conversations_subagents_messages_create": ["Message Subagent", "POST", "outbound"],
    "agents_conversations_tool_servers_list": ["Conversation Tool Servers", "GET", "read"],
    "agents_conversations_tool_servers_reconnect": ["Reconnect Tool Server", "POST", "write"],
    "agents_conversations_update": ["Update Conversation", "PATCH", "write"],
    "agents_conversations_usage": ["Conversation Usage", "GET", "read"],
    "agents_conversations_withdraw_question": ["Withdraw Question", "POST", "write"],
    "agents_create": ["Create Agent", "POST", "write"],
    "agents_delete": ["Delete Agent", "DELETE", "destructive"],
    "agents_get": ["Get Agent", "GET", "read"],
    "agents_grants_delete": ["Revoke Grant", "DELETE", "destructive"],
    "agents_jobs_list": ["List Jobs", "GET", "read"],
    "agents_list": ["List Agents", "GET", "read"],
    "agents_memory": ["List Memory", "GET", "read"],
    "agents_memory_delete": ["Delete Memory", "DELETE", "destructive"],
    "agents_memory_get": ["Read Memory", "GET", "read"],
    "agents_memory_replace": ["Save Memory", "PUT", "write"],
    "agents_memory_versions_get": ["Read Memory Version", "GET", "read"],
    "agents_memory_versions_list": ["List Memory Versions", "GET", "read"],
    "agents_memory_versions_restore": ["Restore Memory Version", "POST", "write"],
    "agents_messages_create": ["Send Message", "POST", "outbound"],
    "agents_model_switch": ["Switch Model", "POST", "write"],
    "agents_moves_cancel": ["Cancel Move", "POST", "write"],
    "agents_moves_get": ["Get Move", "GET", "read"],
    "agents_moves_sign_ins_post": ["Connect Sign In", "POST", "write"],
    "agents_pause": ["Pause Agent", "POST", "write"],
    "agents_rehearsals_create": ["Rehearse", "POST", "write"],
    "agents_resume": ["Resume Agent", "POST", "write"],
    "agents_share": ["Get Share", "GET", "read"],
    "agents_share_messages_create": ["Visitor Message", "POST", "outbound"],
    "agents_share_messages_get": ["Visitor Reply", "GET", "read"],
    "agents_share_post": ["Turn On", "POST", "outbound"],
    "agents_share_rotate": ["Rotate Share", "POST", "write"],
    "agents_share_update": ["Update Share", "PATCH", "write"],
    "agents_states_list": ["Agent States", "GET", "read"],
    "agents_tool_access": ["Get Tool Access", "GET", "read"],
    "agents_tool_servers_connect_link": ["Tool Server Connect Link", "POST", "write"],
    "agents_tool_servers_create": ["Add Tool Server", "POST", "write"],
    "agents_tool_servers_delete": ["Remove Tool Server", "DELETE", "destructive"],
    "agents_tool_servers_list": ["List Tool Servers", "GET", "read"],
    "agents_tool_servers_update": ["Update Tool Server", "PATCH", "write"],
    "agents_triggers_create": ["Add Trigger", "POST", "write"],
    "agents_triggers_delete": ["Remove Trigger", "DELETE", "destructive"],
    "agents_triggers_list": ["List Triggers", "GET", "read"],
    "agents_triggers_pause": ["Pause Trigger", "POST", "write"],
    "agents_triggers_resume": ["Resume Trigger", "POST", "write"],
    "agents_triggers_test": ["Rehearse Trigger", "POST", "write"],
    "agents_triggers_update": ["Update Trigger", "PATCH", "write"],
    "agents_update": ["Update Agent", "PATCH", "write"],
    "agents_wakeups_cancel": ["Cancel Wakeup", "POST", "destructive"],
    "agents_wakeups_create": ["Create Wakeup", "POST", "write"],
    "agents_wakeups_get": ["Get Wakeup", "GET", "read"],
    "agents_wakeups_list": ["List Wakeups", "GET", "read"],
    "agents_wakeups_update": ["Update Wakeup", "PATCH", "write"],
    "agents_workspace": ["List Files", "GET", "read"],
    "agents_workspace_files_delete": ["Delete File", "DELETE", "write"],
    "agents_workspace_files_list": ["Read File", "GET", "read"],
    "agents_workspace_files_replace": ["Write File", "PUT", "write"],
    "agents_workspace_url": ["File Url", "GET", "read"],
    "ai_chat_completions_create": ["Chat Completions", "POST", "write"],
    "ai_embeddings_create": ["Create Embeddings", "POST", "write"],
    "ai_images_create": ["Create Image", "POST", "write"],
    "ai_models_list": ["List Models", "GET", "read"],
    "ai_responses_create": ["Create Response", "POST", "write"],
    "ai_transcriptions_create": ["Create Transcription", "POST", "write"],
    "ai_videos_create": ["Create Video", "POST", "write"],
    "approvals_get": ["Get Approval", "GET", "read"],
    "approvals_list": ["List Approvals", "GET", "read"],
    "approvals_policy": ["Get Approval Policy", "GET", "read"],
    "approvals_policy_changes_list": ["List Approval Policy Changes", "GET", "read"],
    "approvals_policy_explain": ["Explain Approval Policy", "POST", "read"],
    "attachments_delete": ["Delete Attachment", "DELETE", "destructive"],
    "attachments_list": ["List Attachments", "GET", "read"],
    "brand": ["Get Brand", "GET", "read"],
    "brand_delete": ["Reset Brand", "DELETE", "destructive"],
    "brand_replace": ["Put Brand", "PUT", "write"],
    "brand_update": ["Patch Brand", "PATCH", "write"],
    "browser_profiles_create": ["Create Profile", "POST", "write"],
    "browser_profiles_delete": ["Delete Profile", "DELETE", "destructive"],
    "browser_profiles_get": ["Get Profile", "GET", "read"],
    "browser_profiles_list": ["List Profiles", "GET", "read"],
    "browser_profiles_login": ["Login", "POST", "outbound"],
    "browser_profiles_sites_delete": ["Forget Site", "DELETE", "destructive"],
    "browsers_act": ["Act", "POST", "outbound"],
    "browsers_content": ["Page Content", "GET", "read"],
    "browsers_create": ["Create Browser", "POST", "write"],
    "browsers_delete": ["Close Browser", "DELETE", "write"],
    "browsers_extract": ["Extract", "POST", "read"],
    "browsers_get": ["Get Browser", "GET", "read"],
    "browsers_goto": ["Goto", "POST", "outbound"],
    "browsers_list": ["List Browsers", "GET", "read"],
    "browsers_screenshot": ["Screenshot", "GET", "read"],
    "buckets_create": ["Create Bucket", "POST", "write"],
    "buckets_delete": ["Delete Bucket", "DELETE", "destructive"],
    "buckets_export": ["Export Bucket", "POST", "write"],
    "buckets_get": ["Get Bucket", "GET", "read"],
    "buckets_list": ["List Buckets", "GET", "read"],
    "buckets_notifications_create": ["Notify", "POST", "write"],
    "buckets_notifications_remove": ["Stop Notifying", "POST", "write"],
    "buckets_objects_delete": ["Remove Object", "DELETE", "write"],
    "buckets_objects_list": ["List Or Read Objects", "GET", "read"],
    "buckets_objects_replace": ["Put Object", "PUT", "write"],
    "buckets_objects_versions_list": ["Object Versions", "GET", "read"],
    "buckets_objects_versions_restore": ["Restore Object Version", "POST", "write"],
    "buckets_signed_urls_create": ["Signed Url", "POST", "read"],
    "buckets_update": ["Update Bucket", "PATCH", "write"],
    "buckets_uploads_abort": ["Abort Upload", "POST", "write"],
    "buckets_uploads_complete": ["Complete Upload", "POST", "write"],
    "buckets_uploads_create": ["Start Upload", "POST", "write"],
    "buckets_uploads_part_urls_create": ["Upload Part Urls", "POST", "write"],
    "builder_skills_create": ["Create Builder Skill", "POST", "write"],
    "builder_skills_delete": ["Delete Builder Skill", "DELETE", "destructive"],
    "builder_skills_get": ["Get Builder Skill", "GET", "read"],
    "builder_skills_list": ["List Builder Skills", "GET", "read"],
    "builder_skills_update": ["Update Builder Skill", "PATCH", "write"],
    "cards_close": ["Close", "POST", "destructive"],
    "cards_create": ["Create Card", "POST", "spend"],
    "cards_freeze": ["Freeze", "POST", "write"],
    "cards_funding": ["Funding", "GET", "read"],
    "cards_get": ["Get Card", "GET", "read"],
    "cards_list": ["List Cards", "GET", "read"],
    "cards_merchant_categories_list": ["Merchant Categories", "GET", "read"],
    "cards_program": ["Get Program", "GET", "read"],
    "cards_transactions_dispute": ["Dispute", "POST", "outbound"],
    "cards_transactions_get": ["Get Transaction", "GET", "read"],
    "cards_transactions_list": ["Transactions", "GET", "read"],
    "cards_unfreeze": ["Unfreeze", "POST", "sensitive"],
    "cards_update": ["Update Card", "PATCH", "write"],
    "channels_attachments_create": ["Upload Attachment", "POST", "write"],
    "channels_bookmarks_create": ["Add Bookmark", "POST", "write"],
    "channels_bookmarks_delete": ["Remove Bookmark", "DELETE", "write"],
    "channels_bookmarks_list": ["List Bookmarks", "GET", "read"],
    "channels_bookmarks_update": ["Update Bookmark", "PATCH", "write"],
    "channels_close": ["Close Channel", "POST", "destructive"],
    "channels_create": ["Create Channel", "POST", "write"],
    "channels_delete": ["Delete Channel", "DELETE", "destructive"],
    "channels_files_list": ["List Files", "GET", "read"],
    "channels_get": ["Get Channel", "GET", "read"],
    "channels_join": ["Join Channel", "POST", "write"],
    "channels_leave": ["Leave Channel", "POST", "write"],
    "channels_links_list": ["List Links", "GET", "read"],
    "channels_list": ["List Channels", "GET", "read"],
    "channels_members_create": ["Add Member", "POST", "write"],
    "channels_members_delete": ["Remove Member", "DELETE", "destructive"],
    "channels_messages_create": ["Post Message", "POST", "outbound"],
    "channels_messages_follow": ["Follow Thread", "POST", "write"],
    "channels_messages_follow_delete": ["Unfollow Thread", "DELETE", "write"],
    "channels_messages_get": ["Get Message", "GET", "read"],
    "channels_messages_list": ["List Messages", "GET", "read"],
    "channels_messages_pin": ["Pin Message", "POST", "write"],
    "channels_messages_pin_delete": ["Unpin Message", "DELETE", "write"],
    "channels_messages_reactions_create": ["React", "POST", "write"],
    "channels_messages_reactions_delete": ["Unreact", "DELETE", "write"],
    "channels_messages_read": ["Read Thread", "POST", "write"],
    "channels_messages_replies_list": ["List Replies", "GET", "read"],
    "channels_mute": ["Mute Channel", "POST", "write"],
    "channels_mute_delete": ["Unmute Channel", "DELETE", "write"],
    "channels_pins_list": ["List Pins", "GET", "read"],
    "channels_read": ["Mark Read", "POST", "write"],
    "channels_reopen": ["Reopen Channel", "POST", "write"],
    "channels_sections_list": ["Get Sections", "GET", "read"],
    "channels_sections_replace": ["Save Sections", "PUT", "write"],
    "channels_star": ["Star Channel", "POST", "write"],
    "channels_star_delete": ["Unstar Channel", "DELETE", "write"],
    "channels_subscriptions_create": ["Subscribe", "POST", "write"],
    "channels_subscriptions_delete": ["Unsubscribe", "DELETE", "destructive"],
    "channels_subscriptions_get": ["Get Subscription", "GET", "read"],
    "channels_subscriptions_list": ["List Subscriptions", "GET", "read"],
    "channels_threads_list": ["List Threads", "GET", "read"],
    "channels_triggers_create": ["Add Channel Trigger", "POST", "write"],
    "channels_triggers_delete": ["Remove Channel Trigger", "DELETE", "destructive"],
    "channels_triggers_list": ["List Channel Triggers", "GET", "read"],
    "channels_update": ["Update Channel", "PATCH", "write"],
    "checkout_sessions_cancel": ["Cancel Checkout Session", "POST", "write"],
    "checkout_sessions_complete": ["Complete Checkout Session", "POST", "write"],
    "checkout_sessions_create": ["Create Checkout Session", "POST", "write"],
    "checkout_sessions_get": ["Get Checkout Session", "GET", "read"],
    "compute": ["List Compute", "GET", "read"],
    "connected_apps_update": ["Update Connected App", "PATCH", "write"],
    "connections_chat_profiles_list": ["Chat Profiles", "GET", "read"],
    "connections_connect_links_create": ["Create Connect Link", "POST", "write"],
    "connections_create": ["Create Connection", "POST", "write"],
    "connections_delete": ["Delete Connection", "DELETE", "destructive"],
    "connections_get": ["Get Connection", "GET", "read"],
    "connections_list": ["List Connections", "GET", "read"],
    "connections_lookup": ["Lookup", "POST", "read"],
    "connections_operations_run": ["Run Connection Operation", "POST", "outbound"],
    "connections_require_approval": ["Require Approval", "POST", "write"],
    "connections_require_approval_delete": ["Lift Approval", "DELETE", "write"],
    "connections_test_account": ["Mark Test Account", "POST", "write"],
    "connections_update": ["Rename Connection", "PATCH", "write"],
    "connections_usage": ["Connection Usage", "GET", "read"],
    "connections_verify": ["Verify Connection", "POST", "read"],
    "databases_branches_create": ["Branch", "POST", "write"],
    "databases_branches_list": ["List Branches", "GET", "read"],
    "databases_connection_url": ["Connection Url", "POST", "write"],
    "databases_create": ["Create Database", "POST", "write"],
    "databases_delete": ["Delete Database", "DELETE", "destructive"],
    "databases_export": ["Export Database", "POST", "write"],
    "databases_get": ["Get Database", "GET", "read"],
    "databases_list": ["List Databases", "GET", "read"],
    "databases_migrations_create": ["Migrate", "POST", "write"],
    "databases_migrations_list": ["List Migrations", "GET", "read"],
    "databases_query": ["Query", "POST", "write"],
    "databases_restore": ["Restore", "POST", "destructive"],
    "databases_schema": ["Schema", "GET", "read"],
    "delete_previews_create": ["Preview Deletion", "POST", "read"],
    "deployments_cancel": ["Cancel Deployment", "POST", "destructive"],
    "deployments_check": ["Check Deployment", "POST", "write"],
    "deployments_get": ["Get Deployment", "GET", "read"],
    "deployments_logs_list": ["Deployment Logs", "GET", "read"],
    "deployments_promote": ["Promote Deployment", "POST", "write"],
    "deployments_requests_list": ["Deployment Requests", "GET", "read"],
    "deploys_create": ["Deploy Repository", "POST", "write"],
    "dicts_clear": ["Clear Dict", "POST", "destructive"],
    "dicts_create": ["Create Dict", "POST", "write"],
    "dicts_delete": ["Delete Dict", "DELETE", "destructive"],
    "dicts_export": ["Export Dict", "POST", "write"],
    "dicts_get": ["Get Dict", "GET", "read"],
    "dicts_history": ["Dict History", "GET", "read"],
    "dicts_history_restore": ["Restore Dict Entry", "POST", "write"],
    "dicts_items_create": ["Put Items", "POST", "write"],
    "dicts_items_delete": ["Remove Item", "DELETE", "write"],
    "dicts_items_get": ["Get Item", "GET", "read"],
    "dicts_items_increment": ["Increment", "POST", "write"],
    "dicts_items_list": ["List Items", "GET", "read"],
    "dicts_items_replace": ["Put Item", "PUT", "write"],
    "dicts_list": ["List Dicts", "GET", "read"],
    "domains_agreement": ["Agreement", "GET", "read"],
    "domains_connect": ["Connect", "POST", "write"],
    "domains_create": ["Buy", "POST", "spend"],
    "domains_delete": ["Delete Domain", "DELETE", "destructive"],
    "domains_dns_create": ["Dns Set", "POST", "write"],
    "domains_dns_delete": ["Dns Delete", "DELETE", "destructive"],
    "domains_dns_list": ["Dns Records", "GET", "read"],
    "domains_get": ["Get Domain", "GET", "read"],
    "domains_list": ["List Domains", "GET", "read"],
    "domains_renew": ["Renew", "POST", "spend"],
    "domains_search": ["Search", "GET", "read"],
    "domains_transfer_in": ["Transfer In", "POST", "spend"],
    "domains_transfer_quote": ["Transfer Quote", "GET", "read"],
    "domains_update": ["Update Domain", "PATCH", "write"],
    "domains_use_noclick_dns_create": ["Use Noclick Dns", "POST", "write"],
    "domains_verify": ["Verify", "POST", "write"],
    "estimates_create": ["Estimate Monthly Cost", "POST", "read"],
    "estimates_kinds_list": ["List Estimate Kinds", "GET", "read"],
    "events_get": ["Get Event", "GET", "read"],
    "events_list": ["List Events", "GET", "read"],
    "events_types_list": ["Event Types", "GET", "read"],
    "feedback": ["Send Feedback", "POST", "write"],
    "harnesses_list": ["List Harnesses", "GET", "read"],
    "harnesses_models_list": ["List Harness Models", "GET", "read"],
    "humans_owner_answer": ["Get Answer", "GET", "read"],
    "humans_owner_answer_post": ["Set Answer", "POST", "write"],
    "humans_owner_email": ["Add Owner Email", "POST", "outbound"],
    "humans_owner_email_confirm": ["Confirm Owner Email", "POST", "outbound"],
    "humans_owner_reach": ["Get Reach", "GET", "read"],
    "humans_requests_create": ["Create Request", "POST", "outbound"],
    "inboxes_create": ["Create Inbox", "POST", "write"],
    "inboxes_delete": ["Delete Inbox", "DELETE", "destructive"],
    "inboxes_get": ["Get Inbox", "GET", "read"],
    "inboxes_list": ["List Inboxes", "GET", "read"],
    "inboxes_messages_create": ["Send", "POST", "outbound"],
    "inboxes_messages_get": ["Get Message", "GET", "read"],
    "inboxes_messages_list": ["List Messages", "GET", "read"],
    "inboxes_messages_reply": ["Reply", "POST", "outbound"],
    "inboxes_threads_get": ["Get Thread", "GET", "read"],
    "inboxes_threads_list": ["List Threads", "GET", "read"],
    "inboxes_update": ["Update Inbox", "PATCH", "write"],
    "inboxes_wait_for": ["Wait For", "POST", "read"],
    "integrations_events_list": ["List Events", "GET", "read"],
    "integrations_get": ["Describe Integration", "GET", "read"],
    "integrations_list": ["List Integrations", "GET", "read"],
    "integrations_operations_get": ["Describe Operation", "GET", "read"],
    "integrations_operations_list": ["List Operations", "GET", "read"],
    "keys_update": ["Update Key", "PATCH", "write"],
    "machines_agents_list": ["List Agents", "GET", "read"],
    "machines_create": ["Create Machine", "POST", "spend"],
    "machines_delete": ["Delete Machine", "DELETE", "destructive"],
    "machines_exec": ["Exec Command", "POST", "write"],
    "machines_files_list": ["Read File", "GET", "read"],
    "machines_files_replace": ["Write File", "PUT", "write"],
    "machines_get": ["Get Machine", "GET", "read"],
    "machines_list": ["List Machines", "GET", "read"],
    "machines_ports_create": ["Expose Port", "POST", "write"],
    "machines_ports_delete": ["Close Port", "DELETE", "write"],
    "machines_restart": ["Restart Machine", "POST", "write"],
    "machines_sizes_list": ["List Sizes", "GET", "read"],
    "machines_start": ["Start Machine", "POST", "write"],
    "machines_stop": ["Stop Machine", "POST", "write"],
    "machines_update": ["Update Machine", "PATCH", "write"],
    "machines_vetting": ["Get Vetting", "GET", "read"],
    "mcp_servers_clients_list": ["List Clients", "GET", "read"],
    "mcp_servers_create": ["Create Server", "POST", "write"],
    "mcp_servers_delete": ["Delete Server", "DELETE", "destructive"],
    "mcp_servers_get": ["Get Server", "GET", "read"],
    "mcp_servers_list": ["List Servers", "GET", "read"],
    "mcp_servers_rotate": ["Rotate Server", "POST", "write"],
    "mcp_servers_update": ["Update Server", "PATCH", "write"],
    "me_workspaces_list": ["My Workspaces", "GET", "read"],
    "memories_create": ["Create Memory", "POST", "write"],
    "memories_delete": ["Delete Memory", "DELETE", "destructive"],
    "memories_entries_delete": ["Forget Entry", "DELETE", "destructive"],
    "memories_entries_get": ["Read Entry", "GET", "read"],
    "memories_entries_list": ["List Entries", "GET", "read"],
    "memories_entries_replace": ["Save Entry", "PUT", "write"],
    "memories_entries_versions_get": ["Read Entry Version", "GET", "read"],
    "memories_entries_versions_list": ["List Entry Versions", "GET", "read"],
    "memories_entries_versions_restore": ["Restore Entry Version", "POST", "write"],
    "memories_get": ["Get Memory", "GET", "read"],
    "memories_list": ["List Memories", "GET", "read"],
    "memories_update": ["Update Memory", "PATCH", "write"],
    "moves_current": ["Current", "GET", "read"],
    "moves_current_checkout_replace": ["Put Checkout", "PUT", "write"],
    "moves_current_consent_replace": ["Put Consent", "PUT", "write"],
    "moves_current_files_replace": ["Put File", "PUT", "write"],
    "moves_current_finish": ["Finish", "POST", "write"],
    "moves_current_instructions_replace": ["Put Instructions", "PUT", "write"],
    "moves_current_mcp_servers_replace": ["Put Mcp Server", "PUT", "write"],
    "moves_current_memories_replace": ["Put Memory", "PUT", "write"],
    "moves_current_note_replace": ["Put Note", "PUT", "write"],
    "moves_current_plan_link": ["Plan Link", "POST", "write"],
    "moves_current_repo": ["Repo", "POST", "write"],
    "moves_current_secrets_replace": ["Put Secret", "PUT", "write"],
    "moves_current_session_replace": ["Put Session", "PUT", "write"],
    "moves_current_setup_replace": ["Put Setup", "PUT", "write"],
    "moves_current_skills_replace": ["Put Skill", "PUT", "write"],
    "moves_current_source_replace": ["Set Source", "PUT", "write"],
    "notifications_list": ["Get Notifications", "GET", "read"],
    "notifications_update": ["Update Notifications", "PATCH", "write"],
    "operations_cancel": ["Cancel Operation", "POST", "destructive"],
    "operations_get": ["Get Operation", "GET", "read"],
    "operations_list": ["List Operations", "GET", "read"],
    "operations_summary": ["Operations Summary", "GET", "read"],
    "operations_tool_calls_list": ["Operation Tool Calls", "GET", "read"],
    "operations_undo": ["Undo Operation", "POST", "write"],
    "operations_updates_list": ["List Job Updates", "GET", "read"],
    "operations_wait": ["Wait Operation", "GET", "read"],
    "phone_numbers_answer": ["Answer Number", "POST", "write"],
    "phone_numbers_available": ["Search Numbers", "GET", "read"],
    "phone_numbers_calls_create": ["Place Call", "POST", "outbound"],
    "phone_numbers_calls_get": ["Get Call", "GET", "read"],
    "phone_numbers_calls_hang_up": ["Hang Up Call", "POST", "write"],
    "phone_numbers_calls_list": ["List Calls", "GET", "read"],
    "phone_numbers_connect": ["Connect Number", "POST", "write"],
    "phone_numbers_connectable": ["Connectable Numbers", "GET", "read"],
    "phone_numbers_coverage": ["Number Coverage", "GET", "read"],
    "phone_numbers_create": ["Buy Number", "POST", "spend"],
    "phone_numbers_delete": ["Release Number", "DELETE", "destructive"],
    "phone_numbers_disconnect": ["Disconnect Number", "POST", "destructive"],
    "phone_numbers_documents_create": ["Upload Document", "POST", "write"],
    "phone_numbers_get": ["Get Number", "GET", "read"],
    "phone_numbers_list": ["List Numbers", "GET", "read"],
    "phone_numbers_orders_get": ["Get Order", "GET", "read"],
    "phone_numbers_orders_resubmit": ["Resubmit Order", "POST", "write"],
    "phone_numbers_places_list": ["Number Places", "GET", "read"],
    "phone_numbers_port_in": ["Port In", "POST", "spend"],
    "phone_numbers_port_in_retry": ["Retry Port", "POST", "write"],
    "phone_numbers_texts_list": ["List Texts", "GET", "read"],
    "phone_numbers_update": ["Update Number", "PATCH", "write"],
    "policies_list": ["List Policies", "GET", "read"],
    "policy": ["Get Policy", "GET", "read"],
    "policy_add": ["Add Rules", "POST", "sensitive"],
    "policy_evaluate": ["Evaluate", "POST", "read"],
    "policy_remove": ["Remove Rules", "POST", "sensitive"],
    "policy_replace": ["Put Policy", "PUT", "sensitive"],
    "popups_list": ["Get Popups", "GET", "read"],
    "popups_update": ["Update Popups", "PATCH", "write"],
    "projects_account_key": ["Get Account Key", "GET", "read"],
    "projects_account_key_replace": ["Give Account Key", "PUT", "write"],
    "projects_account_key_revoke": ["Revoke Account Key", "POST", "write"],
    "projects_account_key_rotate": ["Rotate Account Key", "POST", "write"],
    "projects_analytics_list": ["Project Analytics", "GET", "read"],
    "projects_analytics_summary": ["Projects Analytics Summary", "GET", "read"],
    "projects_bindings_create": ["Bind", "POST", "write"],
    "projects_bindings_delete": ["Unbind", "DELETE", "destructive"],
    "projects_bindings_get": ["Get Binding", "GET", "read"],
    "projects_bindings_list": ["List Bindings", "GET", "read"],
    "projects_create": ["Create Project", "POST", "write"],
    "projects_current": ["Current Project", "GET", "read"],
    "projects_current_resources_create": ["Resolve Resource", "POST", "write"],
    "projects_delete": ["Delete Project", "DELETE", "destructive"],
    "projects_deployments_create": ["Deploy", "POST", "write"],
    "projects_deployments_list": ["List Deployments", "GET", "read"],
    "projects_domains_create": ["Add Domain", "POST", "write"],
    "projects_domains_delete": ["Remove Domain", "DELETE", "destructive"],
    "projects_domains_list": ["List Domains", "GET", "read"],
    "projects_durable_objects_delete": ["Delete Durable Object Class", "DELETE", "destructive"],
    "projects_durable_objects_list": ["List Durable Objects", "GET", "read"],
    "projects_durable_objects_objects_list": ["List Durable Object Instances", "GET", "read"],
    "projects_email": ["Email Status", "GET", "read"],
    "projects_email_broadcasts_create": ["Broadcast", "POST", "outbound"],
    "projects_email_codes_create": ["Send Code", "POST", "outbound"],
    "projects_email_messages_list": ["Email Messages", "GET", "read"],
    "projects_email_post": ["Enable Email", "POST", "write"],
    "projects_email_resubscribe": ["Resubscribe", "POST", "write"],
    "projects_email_send": ["Send Email", "POST", "outbound"],
    "projects_export": ["Export Project", "POST", "write"],
    "projects_get": ["Get Project", "GET", "read"],
    "projects_list": ["List Projects", "GET", "read"],
    "projects_live": ["Get Live", "GET", "read"],
    "projects_live_changes_create": ["Hand Off", "POST", "outbound"],
    "projects_live_coder": ["Get Coder", "GET", "read"],
    "projects_live_detach": ["Detach", "POST", "write"],
    "projects_live_edits_list": ["List Edits", "GET", "read"],
    "projects_live_end": ["End Session", "POST", "write"],
    "projects_live_enter_links_create": ["Enter Link", "POST", "write"],
    "projects_live_exec": ["Exec Command", "POST", "write"],
    "projects_live_sessions_create": ["Start Session", "POST", "write"],
    "projects_logs_list": ["Project Logs", "GET", "read"],
    "projects_payments_create": ["Enable Payments", "POST", "write"],
    "projects_payments_list": ["Payments Status", "GET", "read"],
    "projects_previews_link": ["Preview Link", "POST", "write"],
    "projects_previews_links_revoke": ["Revoke Preview Links", "POST", "write"],
    "projects_public": ["Make Public", "POST", "write"],
    "projects_public_delete": ["Make Private", "DELETE", "write"],
    "projects_schedules_create": ["Put Schedule", "POST", "write"],
    "projects_schedules_list": ["List Schedules", "GET", "read"],
    "projects_secrets_delete": ["Delete Secret", "DELETE", "destructive"],
    "projects_secrets_list": ["List Secrets", "GET", "read"],
    "projects_secrets_versions_list": ["Project Secret Versions", "GET", "read"],
    "projects_secrets_versions_restore": ["Restore Project Secret", "POST", "write"],
    "projects_settings_delete": ["Delete Setting", "DELETE", "write"],
    "projects_settings_list": ["List Settings", "GET", "read"],
    "projects_settings_replace": ["Set Setting", "PUT", "write"],
    "projects_settings_versions_list": ["Project Setting Versions", "GET", "read"],
    "projects_settings_versions_restore": ["Restore Project Setting", "POST", "write"],
    "projects_sign_in": ["Sign In Status", "GET", "read"],
    "projects_sign_in_post": ["Enable Sign In", "POST", "write"],
    "projects_sign_in_upgrade": ["Upgrade Sign In", "POST", "write"],
    "projects_subscriptions_create": ["Subscribe", "POST", "write"],
    "projects_subscriptions_delete": ["Unsubscribe", "DELETE", "destructive"],
    "projects_subscriptions_deliveries_list": ["List Subscription Deliveries", "GET", "read"],
    "projects_subscriptions_get": ["Get Subscription", "GET", "read"],
    "projects_subscriptions_list": ["List Subscriptions", "GET", "read"],
    "projects_subscriptions_test": ["Send Test Event", "POST", "outbound"],
    "projects_unpublish": ["Unpublish Project", "POST", "write"],
    "projects_update": ["Update Project", "PATCH", "write"],
    "projects_usage": ["Project Usage", "GET", "read"],
    "queues_clear": ["Clear Queue", "POST", "destructive"],
    "queues_create": ["Create Queue", "POST", "write"],
    "queues_dead_letters_delete": ["Discard", "DELETE", "write"],
    "queues_dead_letters_list": ["Dead Letters", "GET", "read"],
    "queues_dead_letters_retry": ["Retry", "POST", "write"],
    "queues_delete": ["Delete Queue", "DELETE", "destructive"],
    "queues_depth": ["Depth History", "GET", "read"],
    "queues_export": ["Export Queue", "POST", "write"],
    "queues_get": ["Get Queue", "GET", "read"],
    "queues_list": ["List Queues", "GET", "read"],
    "queues_messages_ack": ["Ack", "POST", "write"],
    "queues_messages_create": ["Put Messages", "POST", "write"],
    "queues_messages_get": ["Get Message", "GET", "read"],
    "queues_messages_list": ["Take Messages", "GET", "write"],
    "queues_messages_nack": ["Nack", "POST", "write"],
    "queues_messages_release": ["Release", "POST", "write"],
    "queues_update": ["Update Queue", "PATCH", "write"],
    "quotes_create": ["Create Quote", "POST", "read"],
    "quotes_get": ["Get Quote", "GET", "read"],
    "quotes_kinds_list": ["Quote Kinds", "GET", "read"],
    "quotes_purchase": ["Purchase Quote", "POST", "write"],
    "referral": ["Get Referral", "GET", "read"],
    "referral_apply": ["Apply Referral", "POST", "write"],
    "regions_list": ["List Regions", "GET", "read"],
    "render": ["Create Render", "POST", "write"],
    "repos_backups_list": ["List Backups", "GET", "read"],
    "repos_backups_restore": ["Restore Backup", "POST", "write"],
    "repos_branches_list": ["Branches", "GET", "read"],
    "repos_branches_update": ["Move Branch", "PATCH", "write"],
    "repos_clone_url": ["Clone Url", "POST", "write"],
    "repos_commits_create": ["Commit", "POST", "write"],
    "repos_commits_get": ["Commit Changes", "GET", "read"],
    "repos_commits_list": ["History", "GET", "read"],
    "repos_create": ["Create Repo", "POST", "write"],
    "repos_delete": ["Delete Repo", "DELETE", "destructive"],
    "repos_export": ["Export Repo", "POST", "write"],
    "repos_files_list": ["Files", "GET", "read"],
    "repos_get": ["Get Repo", "GET", "read"],
    "repos_list": ["List Repos", "GET", "read"],
    "requests_list": ["List Requests", "GET", "read"],
    "run": ["Run", "POST", "outbound"],
    "sandboxes_create": ["Create Sandbox", "POST", "write"],
    "sandboxes_delete": ["Delete Sandbox", "DELETE", "destructive"],
    "sandboxes_exec": ["Exec Command", "POST", "write"],
    "sandboxes_files_list": ["Read File", "GET", "read"],
    "sandboxes_files_replace": ["Write File", "PUT", "write"],
    "sandboxes_get": ["Get Sandbox", "GET", "read"],
    "sandboxes_list": ["List Sandboxes", "GET", "read"],
    "schedules_delete": ["Delete Schedule", "DELETE", "destructive"],
    "schedules_get": ["Get Schedule", "GET", "read"],
    "schedules_pause": ["Pause Schedule", "POST", "write"],
    "schedules_resume": ["Resume Schedule", "POST", "write"],
    "schedules_run": ["Run Schedule", "POST", "write"],
    "secrets_create": ["Create Secret", "POST", "write"],
    "secrets_delete": ["Delete Secret", "DELETE", "destructive"],
    "secrets_get": ["Get Secret", "GET", "read"],
    "secrets_list": ["List Secrets", "GET", "read"],
    "secrets_versions_list": ["Secret Versions", "GET", "read"],
    "secrets_versions_restore": ["Restore Secret", "POST", "write"],
    "skills_create": ["Create Skill", "POST", "write"],
    "skills_delete": ["Delete Skill", "DELETE", "destructive"],
    "skills_files_list": ["Read Files", "GET", "read"],
    "skills_get": ["Get Skill", "GET", "read"],
    "skills_list": ["List Skills", "GET", "read"],
    "skills_update": ["Update Skill", "PATCH", "write"],
    "skills_versions_create": ["Save Version", "POST", "write"],
    "skills_versions_get": ["Get Version", "GET", "read"],
    "skills_versions_list": ["List Versions", "GET", "read"],
    "skills_versions_restore": ["Restore Version", "POST", "write"],
    "status": ["Get Status", "GET", "read"],
    "step_types_get": ["Get Step Type", "GET", "read"],
    "step_types_list": ["List Step Types", "GET", "read"],
    "step_types_output_shape": ["Get Step Output Shape", "GET", "read"],
    "texting_registrations_create": ["Create Registration", "POST", "spend"],
    "texting_registrations_delete": ["Delete Registration", "DELETE", "destructive"],
    "texting_registrations_get": ["Get Registration", "GET", "read"],
    "texting_registrations_list": ["List Registrations", "GET", "read"],
    "texting_registrations_update": ["Correct Registration", "PATCH", "write"],
    "texting_registrations_verify": ["Verify Registration", "POST", "write"],
    "tool_calls_list": ["List Tool Calls", "GET", "read"],
    "tool_calls_summary": ["Tool Calls Summary", "GET", "read"],
    "toolkits_call": ["Call Tool", "POST", "outbound"],
    "toolkits_definitions_create": ["Tool Definitions", "POST", "read"],
    "trash": ["List Trash", "GET", "read"],
    "trash_delete": ["Purge", "DELETE", "destructive"],
    "trash_get": ["Get Item", "GET", "read"],
    "trash_restore": ["Restore", "POST", "write"],
    "usage": ["Get Usage", "GET", "read"],
    "usage_limits_account_replace": ["Set Account Cap", "PUT", "write"],
    "usage_limits_list": ["Get Usage Limits", "GET", "read"],
    "usage_series_list": ["Get Usage Series", "GET", "read"],
    "users_create": ["Create User", "POST", "write"],
    "users_delete": ["Delete User", "DELETE", "destructive"],
    "users_export": ["Export User", "POST", "write"],
    "users_get": ["Get User", "GET", "read"],
    "users_list": ["List Users", "GET", "read"],
    "users_phone_check": ["Check User Phone", "POST", "write"],
    "users_phone_verify": ["Verify User Phone", "POST", "outbound"],
    "users_spending_pause": ["Pause Spending", "POST", "write"],
    "users_spending_resume": ["Resume Spending", "POST", "sensitive"],
    "users_suspend": ["Suspend User", "POST", "write"],
    "users_update": ["Update User", "PATCH", "write"],
    "volumes_copy": ["Copy Files", "POST", "write"],
    "volumes_create": ["Create Volume", "POST", "write"],
    "volumes_delete": ["Delete Volume", "DELETE", "destructive"],
    "volumes_export": ["Export Volume", "POST", "write"],
    "volumes_files_delete": ["Remove Files", "DELETE", "write"],
    "volumes_files_list": ["Read Files", "GET", "read"],
    "volumes_files_replace": ["Write File", "PUT", "write"],
    "volumes_get": ["Get Volume", "GET", "read"],
    "volumes_list": ["List Volumes", "GET", "read"],
    "webhooks_create": ["Create Webhook", "POST", "write"],
    "webhooks_delete": ["Delete Webhook", "DELETE", "destructive"],
    "webhooks_deliveries_list": ["List Deliveries", "GET", "read"],
    "webhooks_deliveries_redeliver": ["Redeliver", "POST", "outbound"],
    "webhooks_get": ["Get Webhook", "GET", "read"],
    "webhooks_list": ["List Webhooks", "GET", "read"],
    "webhooks_test": ["Test Webhook", "POST", "outbound"],
    "webhooks_update": ["Update Webhook", "PATCH", "write"],
    "workflow_examples_get": ["Get Workflow Example", "GET", "read"],
    "workflow_examples_list": ["List Workflow Examples", "GET", "read"],
    "workflows_approvals_get": ["Get Workflow Approval", "GET", "read"],
    "workflows_approvals_list": ["List Workflow Approvals", "GET", "read"],
    "workflows_builds_answer": ["Answer Build", "POST", "write"],
    "workflows_builds_create": ["Start Build", "POST", "write"],
    "workflows_create": ["Create Workflow", "POST", "write"],
    "workflows_delete": ["Delete Workflow", "DELETE", "destructive"],
    "workflows_drafts_create": ["Draft Steps", "POST", "write"],
    "workflows_edits_create": ["Edit Workflow", "POST", "write"],
    "workflows_endpoint": ["Call Endpoint", "POST", "outbound"],
    "workflows_endpoint_replace": ["Put Endpoint", "PUT", "outbound"],
    "workflows_endpoint_runs_get": ["Read Endpoint Run", "GET", "read"],
    "workflows_files_delete": ["Delete Workflow File", "DELETE", "destructive"],
    "workflows_files_list": ["List Workflow Files", "GET", "read"],
    "workflows_folders_create": ["Create Workflow Folder", "POST", "write"],
    "workflows_folders_delete": ["Delete Workflow Folder", "DELETE", "write"],
    "workflows_folders_list": ["List Workflow Folders", "GET", "read"],
    "workflows_get": ["Get Workflow", "GET", "read"],
    "workflows_graph": ["Get Workflow Graph", "GET", "read"],
    "workflows_list": ["List Workflows", "GET", "read"],
    "workflows_move": ["Move Workflow", "POST", "write"],
    "workflows_outputs_list": ["Latest Outputs", "GET", "read"],
    "workflows_pause": ["Pause Workflow", "POST", "write"],
    "workflows_rehearsals_create": ["Rehearse Workflow", "POST", "write"],
    "workflows_restore": ["Restore Workflow", "POST", "write"],
    "workflows_resume": ["Resume Workflow", "POST", "write"],
    "workflows_runs_counts_list": ["Count Runs", "GET", "read"],
    "workflows_runs_create": ["Start Run", "POST", "outbound"],
    "workflows_runs_files_list": ["Run Files", "GET", "read"],
    "workflows_runs_get": ["Get Run", "GET", "read"],
    "workflows_runs_list": ["List Runs", "GET", "read"],
    "workflows_runs_stop": ["Stop Run", "POST", "outbound"],
    "workflows_setup": ["Get Workflow Setup", "GET", "read"],
    "workflows_setup_request": ["Request Workflow Setup", "POST", "outbound"],
    "workflows_steps_clear_state": ["Clear Step State", "POST", "write"],
    "workflows_steps_expression": ["Preview Expression", "POST", "read"],
    "workflows_steps_options_create": ["List Step Options", "POST", "read"],
    "workflows_steps_outputs_get": ["Get Step Output", "GET", "read"],
    "workflows_steps_outputs_list": ["List Step Outputs", "GET", "read"],
    "workflows_steps_publish": ["Publish Step", "POST", "write"],
    "workflows_steps_values_create": ["Load Step Value", "POST", "write"],
    "workflows_tables_delete": ["Delete Workflow Table", "DELETE", "destructive"],
    "workflows_tables_list": ["List Workflow Tables", "GET", "read"],
    "workflows_tables_rows_list": ["List Workflow Table Rows", "GET", "read"],
    "workflows_test_runs_list": ["List Test Runs", "GET", "read"],
    "workflows_versions_create": ["Name Workflow Version", "POST", "write"],
    "workflows_versions_get": ["Get Workflow Version", "GET", "read"],
    "workflows_versions_list": ["List Workflow Versions", "GET", "read"],
    "workflows_versions_restore": ["Restore Workflow Version", "POST", "write"],
    "workflows_versions_update": ["Rename Workflow Version", "PATCH", "write"],
    "workspaces_alerts_create": ["Alert Member", "POST", "read"],
    "workspaces_archive": ["Archive Workspace", "POST", "destructive"],
    "workspaces_create": ["Create Workspace", "POST", "write"],
    "workspaces_delete": ["Delete Workspace", "DELETE", "destructive"],
    "workspaces_get": ["Get Workspace", "GET", "read"],
    "workspaces_invite_links_create": ["Create Invite Link", "POST", "write"],
    "workspaces_invites_create": ["Create Invite", "POST", "outbound"],
    "workspaces_invites_delete": ["Revoke Invite", "DELETE", "destructive"],
    "workspaces_invites_list": ["List Invites", "GET", "read"],
    "workspaces_invites_resend": ["Resend Invite", "POST", "outbound"],
    "workspaces_invites_rotate": ["Rotate Invite", "POST", "write"],
    "workspaces_list": ["List Workspaces", "GET", "read"],
    "workspaces_logo_replace": ["Set Logo", "PUT", "write"],
    "workspaces_members_create": ["Add Member", "POST", "write"],
    "workspaces_members_delete": ["Remove Member", "DELETE", "destructive"],
    "workspaces_members_update": ["Update Member", "PATCH", "write"],
    "workspaces_messages_list": ["List Workspace Messages", "GET", "read"],
    "workspaces_noclick": ["Workspace Noclick", "GET", "read"],
    "workspaces_questions_create": ["Ask Space", "POST", "write"],
    "workspaces_questions_list": ["Space Questions", "GET", "read"],
    "workspaces_resources_create": ["Share Resource", "POST", "write"],
    "workspaces_resources_delete": ["Unshare Resource", "DELETE", "destructive"],
    "workspaces_resources_list": ["List Shared Resources", "GET", "read"],
    "workspaces_resources_update": ["Update Shared Resource", "PATCH", "write"],
    "workspaces_subscriptions_create": ["Subscribe", "POST", "write"],
    "workspaces_subscriptions_delete": ["Unsubscribe", "DELETE", "destructive"],
    "workspaces_subscriptions_get": ["Get Subscription", "GET", "read"],
    "workspaces_subscriptions_list": ["List Subscriptions", "GET", "read"],
    "workspaces_summary": ["Workspace Summary", "GET", "read"],
    "workspaces_unarchive": ["Unarchive Workspace", "POST", "write"],
    "workspaces_update": ["Update Workspace", "PATCH", "write"],
    "workstreams_list": ["List Workstreams", "GET", "read"],
    "workstreams_update": ["Update Workstream", "PATCH", "write"],
};

/** The integrations an agent may call operations of, each by its node type without `automation-` (an agent's
 *  tool for one is named by it, `-` as `_`: `google_drive__…`). */
export const AGENT_TOOL_APPS: ReadonlySet<string> = new Set(
    `123formbuilder
2chat
46elks
7shifts
abcgymsales
ably
abyssale
abysshub
accredible-certificates
acculynx
acronis-cyber-protect-cloud-ca18
act-crm
actionstep
active-merge
activecampaign
acuity-scheduling
adafruit-io
adapty
addevent
addressfinder
addresszen
adobe-analytics
adobe-campaign
adyen
adyntel
affinda
affinity
agencyzoom
agent-mail
agenty
agiled
agorapulse
aha
ahrefs
ai-ml-api
aimtell
air
airbyte
airtable
airtop
airwallex
airweave
akeneo
akismet
akkio
akta
alchemy
alegra
algolia
algorand-developer-portal
alpaca
altoviz
alttext-ai
amazing-marvin
amazon-polly
americommerce
amplemarket
amplience
anakin-io
anchor-browser
android-texter
any-db
anymail-finder
apache
apacta
api-bible
api-ninjas
api2cart
api2convert
apiframe
apify
apigee
apilio
apipie-ai
apitemplateio
apiverve
apollo
appcenter
appcircle
apphud
appointedd
appsheet
apptivegrid
apptoto
appwrite
aprimo
arbox
arcads
arize-ax
arthur-online
artificial-analysis
aryeo
asana
ashby
askell
assemblyai
assemblycom
asset-panda
assignar
atlas-admin
atlas-ai-revenue-engine
attentive
attio
audienceful
audiobookshelf
auth0
autotask
avaza
aviato
avoma
award-force
aweber
awork
axonaut
bambooci
bamboohr
bandsintown
bannerbear
base44
basedash
baserow
baseten
basin
batchdialer
bc-gov-news
bclaws
beach-day-api
beaconchain
beatapi
beehiiv
benchmark-email
benchmark-email-classic
benzinga
bettercontact
beyond-presence
bfl
bigcommerce
bigmailer
bigoven
bigquery
bika
bill
billetweb
billingo
binsr-inspect
birdeye
bitbadges
bitly
bitrise
bitsnap
bitwarden
bizzabo
bkper
blackboard
blink
blinq
blitz-api
blooio
bloom-growth
bloomerang
bluebarry
bluefox-email
bluepillow
bluesky
bokun
bold-commerce
boldsign
bolna
bonsai
bonzo
bookeo
booking-experts
bookingmood
bookspot
bookwhen
botcake-1
botconversa
botmaker
botpress
botsonic
botstar
bouncer
bouncie
bouncify
box
brandfetch
brandfolder
braze
breezy-hr
brex
brightcove
brightdata
brilliant-directories
browseai
browserbase-tool
browserless
bsc-designer
btcpay-server
bubbles
bugbug
bugherd
bugsnag
buildinai
buildium
buildkite
builtwith
bulkpublish
bulksmscom
bungie
bunnycdn
burst-sms
burstyai
businessmap
bytescale
cabinpanda
cakemail
cal-com
cal-id
calendly
callerapi
callfire
campaign-cleaner
canada-holidays
canopy
canopy-connect
canva
capgo
captivated
carbone
cardclan
cardly
carsxe
cartgenie
casebook
caspio
cats
centralstationcrm
cert-seal
certifier
certs365
channeladvisor
charla
chaser
chatbase
chatbotkit
chatwoot
check-cherry
checkfront
checkout-com
chili-piper
chmeetings
chorus-by-zoominfo
chroma
churchtools
cin7-core
cinc
circl
circle
circleback
circleci
claid-ai
clay
clearblade
clearout
clerk-io
cleverreach
clevertap
clickfunnels
clickhouse
clicksend
clicksign
clicktime
clickup
cliengo
climate
cling
cliniko
clio
clockify
cloro
closum
cloudbeds
cloudbees
cloudflare
cloudsmith
cloudtalk
cloudzero
clover
cloze
club-os
coassemble
coda
codacy
codat
codesearch
cody
coinapi
coinbase
coingecko
coinmarketcal
coinmarketcap
college-football-data
combell
cometapi
commerce-layer
common-room
commpeak
commusoft
companycam
companyenrich
composio
condens
conductor
configcat
confluence
conjur
connecteam
consignly
constant-contact
consumerfinance
contabo
content-snare
content-studio
contentstack
context-dev
contribly
control-d
conversion-tools
convertapi
converted-da-56088
conveyor
convolo-ai
coolify
cor
corbit-sms
corrently
coveo
cpy
cradl-ai
craftmypdf
credas
credlys-acclaim-platform
creem
crelate
crew-ai
crisp
crossmint
crowdin
crunchbase
csvbox
currents-api
cursor
custify
customerbase
customgpt
cvent
cycat
cyclr
cypher-learning
dacast
dadata-ru
daily
dante-ai
dart
databox
databricks
datadog
dataforseo
datagma
datarobot
daylite
dbt-cloud
dealmachine
debitura
debounce
deel
deepgram
deepimage
deployhq
deputy
dev-cycle
devin
devto
dex
dial
dialpad
diffchecker
digicert
digistore24
digitalocean
directiq
directus
discord
discourse
ditlead
dixa
dnsfilter
dnsimple
dnsmadeeasy
docamatic
dock-certs
docker-engine
docker-hub
docraptor
docsautomator
docsbot-ai
docspell
docugenerate
documenso
docupilot
docuseal
docusign
dodo
doit
dokploy
domainsdb
domo
doorloop
doppler
doqs
dots
dovetail
dpd-connect
dpd2
dragn-survey
dreamstudio
dromo
drop-cowboy
drop-to-cdn
dropbox
dropbox-sign
dropcontact
dropinblog
dub
dust
dux-soup
dv360
dynamic-mockups
dynapictures
dynatrace
e-boekhoudennl
e-conomic
e2b
easy-email-verification
easy-project
easybizy
easybroker-archive
easypromos
ebi
echtpost
eduzz
egestor
egnyte
elai
elastic-email
elasticsearch
elevenlabs
elmah
eloqua
email-on-acid
emaillistverify
emailoctopus
emailvalidation
emelia
emnify
encharge
encircle
enforcedflow
enginemailer
enrich-layer
env0
eodhd-apis
epos-now
esputnik
etermin
etsy
event-tickets
eventify
everflow
everhour
evertransit
everyaction
everypage
evetech
evoliz
evolution-go
exa
excel
exceptionless
exercisecom
exlibrisgroup
exoscale
expedy
expensify
explorium
extend
extole
extrovert
extruct-ai
ez-texting
ezeep-printing
ezekia
facebook
facecheck
factorial
facturadirecta
faktoora
fal
faraday
fareharbor
farmbrite
fathom
fatture-in-cloud
feathr
fec
fellow
felt
fiber
fidel-api
figma
figshare
filepost
filescan
filevine
fillout
financial-datasets-ai
findymail
finmo
finnhub
fireberry
firecrawl
firestore
firmable
fivetran
fixer
fixer-io
flashquotes
flat
flatfile
fleetio
flipdish
flokzu
flowsavvy
flutterwave
fly
folk
followupboss
fomo
force24
forcemanager
forgejo
formaloo
formbricks
formcarry
formspark
formstack
formstep
fountain
foursquare
fourthwall
frame-io-v4
freee
freshsales
freshteam
front
fulcrum
fullenrich
fullstory
function-point
fundraise-up
fungenerators
funnelchat
funnelcockpit
funtranslations
fuseai
futureagi
fxapis
fynk
gainsight-customer-communities
ganttic
geekbot-da51177
geekflare
gender-api
genderapi-io
genesiscloud
geoapify
geocodio
geodatasource
get-the-referral
getaccept
getanyapi
giftbit
giphy
gitea
github-rest
gitlab
givebutter
gladia
glean
gleap
gleif
glide-apps
globalping
glofox
gmail
go-table
go-to-connect
go-to-training
goatcounter
gocardless
gofundme-pro
gohighlevel
gong
good-grants
goodapi-plant-trees
goodbarber
goody
google-ads
google-ai-studio
google-analytics
google-books
google-business-profile
google-calendar
google-chat
google-classroom
google-cloud-natural-language
google-cloud-storage
google-contacts
google-docs
google-drive
google-forms
google-maps
google-meet
google-search-console
google-sheets
google-slides
google-tasks
google-translate
gorgias
gorilladesk
gotify
gotowebinar
gov
gptzero-detect-ai
grafana
granola
graphhopper
greenhouse
griptape
grocy
grok
gsmtasks
gtmetrix
gusto
hackernews
hackmd
hailey-hr
haku
halopsa
handwrytten
happy-scribe
harness
harvey
hasslefreebooks
heartbeat
hedy
hello-tracks
helloasso
here
hetrixtools
hetzner
hevo
hex
heygen
heymarket
higgsfield
highergov
hipaatizer
hitl
hitpay
hive
hivelocity
hiver
hjarni
hlr-lookup
holded
homebase
honeybadger
honeycomb
hookdeck
hospitable
hostfully
housecall-pro
houzz-pro
hover
http-request
httpsms
hubfit
hubflo
hubhopper
hubspot
hubstaff
humanitec
humanitix
humanloop
hunter
huntress
hypeauditor
hyperbrowser
hyros
iclosed
icypeas
id4i
idealpostcodes
idloom
ignav-flights
ignisign
ignition
ilert
image-charts
imagekit-io
imagerouter
imap
immich
implisense-api
inblog
incident-io
increase
infakt
infinity
infisical
inforumobile
infraspeak
inmobalia-crm
inmobile-sms-gateway
insightly
instagram
instamojo
instantly
instapaper
instatus
intelliprint
intercom
intulse
investorbase
investorlift
invofox
invoiceninja
invoicexpress
ionos-hosting-services
ionoscloud
ip2location-io
ip2proxy
ip2whois
ipbase
ipinfo-io
iplocate
ironclad
isn
iterable
itm-platform
jackrabbit-class
jaicob
jev
jigsawstack
jina-reader
jinko
jira
jira-service-management-alert-ca
jira-software-server
jiraservicemanagement
jobadder
jobber
jogg-ai
join-it
joomla
jooto
jq
json2video
jumpcloud
jumpseller
junglescout
just-eat
just-one-api
justcall
jvzoo
jwplayer
kadoa
kajabi
kantataox
kapso
karbon
katana-mrp
keap
keila
kenect-text-messaging
kernel
keycloak
kibana
kick
kieai
kindo
kintone
kisi
kit
kiwify
kizeo-forms
klaviyo
klicktipp
knowify
kobotoolbox
kommo
kontent-ai
koyeb
krisp
kubernetes
kucoin-futures
kudosity
kumpeapps
kvcore
lagrowthmachine
lakera-guard
lambdatest
lamini
landbot
langbase
langflow
langfuse
languagetool
laposta
lara-translate
lassocrm
lattice
launchdarkly
lead-forensics
lead-prosper
leadboxer
leadfeeder
leadmagic
leadsforge
leadsimple
leanix
leap
leap-crm
learnifier
learnworlds
leexi
legalmatch
legl
lemlist
lenz
lessonspace
lettr
lev
levitate
libretranslate
lightspeed
line
linear
linkace
linkedin
linkly
linkup
linkwarden
linode
linq
listclean
listennotes
listrak
liveagent
localazy
lofty
logo-dev
lokalise
lonescale
looker
loops
loopy-loyalty
loyverse
luma
lumapps
lusha
luxury-presence
lytho
magento-v2
magic-hour
magicplan
mailchimp
maildroppa
mailercloud
mailerlite-classic
mailersend
mailgun
mailjet
mailmodo
mailslurp
mailsoftly
maintainx
manifestly
manus
manychat
manyreach
manyrequests
mapbox
marketsharp
marketstack
markup-ai
mastodon
mateo
matillion
mattermost
me-qr-qr-code
mediasilo
meetgeekai
meetstream-ai
meilisearch
melo
mem
mem0
membershipio
memberspot
memelord
mentortools
mercado-pago
mercury
merge-dev
meshy
messagebird
meta
method-crm
metricool
mews
mezmo
microsoft-bookings
microsoft-dynamics365-business-c
microsoft-entra-id
microsoft-exchange
microsoft-graph-api-daemon-app
microsoft-graph-security
microsoft-onenote
microsoft-power-bi
microsoft-powerpoint
microsoft-sharepoint
microsoft-teams
microsoft-teams-events
microsoft-todo
middesk
mighty-networks
mightycall
mihu-ai
milvus
mindbody
mindstamp
minelead
minerstat
mineskin
minimax
mirakl
miro
mist
mixmax
mixpanel-service-account
mobile-message-ca21345
mobile-text-alerts
moco
modern-treasury
modusign
mollie-1
monday
moneybird
mongodb
monta
moonclerk
moskit
motaword
moxo
msg91
mumara
mural
murf
mux
mx-technologies
mycase
mycashflow
mycrm-leads
myotp-app
namsor
nango
nanonets-ocr
nationbuilder
navigatr
nebl
neetocal
neetodesk
neetoform
neetoinvoice
neo4j
neon
neoncrm
net2phone
netbox
nethunt-crm
netlicensing
netlify
neutrino
new-relic
newie
nextcloud
nextdoor
nfusionsolutions
ngrok
nifty-pm
niftyimages
nimbata
ninety
nmkr-studio
nocodb
northflank
notion
notra
nozbe-teams
numverify
nusii-proposals
nutrient-document-web-services-api
nutshell
nylas
oanda
obono
octen
octorate
office-365
okta
ollama
olostep
omnisend
onedesk
onedrive
onelake
onepage-crm
onesignal
onlyoffice-docspace
open-sea
openalex
opencage
opendatasoft
openfigi
openlayer
openpolicy
openstates
openstatus
openwa
operating
opn-form
opsgenie
opusclip
oracle-field-service
oracle-hcm
orgo
orq-ai
orshot
ory
osv
otasync
outlook
outreach
outscraper-ca1391
outseta
owler
ownerrez
paddle
padlet-1
pagerduty
pagespeed
paperform
paradym
parallel
parcellab
parma
parsera
parseur
partnerstack
passkit-membership
past-dev
payaca
payments
paypal
paypro
paystack
pdfco
pdfless
pdq-connect
peach
peaka
peekalink
peerdom
peliqan
pencil-spaces
pennylane
penpot
people-data-labs
perfect-venue
perfex-crm
perigon
permit-io
perplexity
persona
personio
phantombuster
phone
phone-harness
phrase
picsart
pidgeon
pims
pinata
pinecone
pingdom
pinterest
pipedream-connect
pipedrive
pipeless
pipeline-crm
pitchbox
placetel
planable
planday
planetscale
platerecognizer
plaud
plausible
pledge
ploid
pneumatic
pocketsmith
podium
polar
polygon
polymarket
polymarket-us
poma-grill
porkbun
portalio
postal-data-api
postgres
postgrid-print-mail
posthog
postiz
postman
postmark
postnitro
postwire
powerdns
practice-better
precisefp
precisely
predictleads
printful
printify
prisma
process-street
procore
productboard
productify-ai
productlane
productplan
project-broadcast
projul
promptlayer
propertyradar
proposify
proworkflow-nexus
proxiedmail
pulsetic
pulumi
pushcut
pylon-1
qase
qdrant
qomon
qonto
qonversion
qovery
qstash
quadratic
quentn
quickbase
quickbooks
quickchart
quickfile
quiltt
quipuapp
quo
qwilr
ragic
raisely
rally-corp
ramp
rasa
rawg-video-games-database
razorpay
rbaskets
reapit-foundations
rebrandly
recallai
reclaim-ai
recraft
recruitcrm
recruitee
recruiterflow
recurly
reddit
reddit-ads
redirect-pizza
redirection
redis
reducto
refersion
reflect
regiondo
rei-pebble
relevance-ai
reloadify
remote
remove-bg
render
rendi
rentcast
rentec-direct
rentman
repairdesk
repairshopr
repliz
reply
reply-io
resend
resource-guru
responder
responsys
retell-ai
reteno
returnista
reviewflowz
revolut-for-business
rezdy
riddle-quiz-maker
rillet
ringba
ringcentral
ringover
rippling
ritekit
rkvst
roam
roblox
robocorp
rocket-reach
rocketadmin
rocketlane
roezan-sms
rollbar
rootly
rosette-text-analytics
rossum
route4me
royalmail
rss
rudder
rumble
rundeck
runn
runpod
runscope
runsignup
safetyculture
sailpoint
sakari-sms
sales-simplify
salesforce
salesforge
salesloft
salesmsg
salesql
salesrabbit
salesrobot
samanage
samcart
samdock
samsara
sanity
sap-concur
sap-s-4hana-cloud
sapling-ai
saucelabs
savvycal
scale-ai
scalepad
scalr
scheduleonce
schoolmaker
scoro
scrape-do
scrapecreators
scrapegraph-ai
screenshotbase
se-ranking
seam
search-api
search1api
sec
securitytrails
selectpdf
sellercloud
sellsy
semanticscholar
sematext
semrush
send-email
send-pulse
sendbird
sendcloud
sendfox
sendgrid
sendit
sendlane
sendsafely
sendspark
sendx
senta
sentry
seqera
sequenzy
serply
serpstat
sertifier
serverless-function
servicem8
servicetitan
servicetrade
setmore
sevdesk
seven-io
sheetdb
shipengine
shipmondo
shippo
shlink
shopify
shopvox
shortcut
shorten-rest
shortpen
showmojo
showpad
sidetracker
sierra-interactive
sigma
sign-plus
signable
signal8
signalwire
signatureapi
signify
signpath
signrequest
signupgenius
signwell
simla-com
simple-localize
simplero
simplesat
simplicate
simplybook
simplyrets
simpro
singlestore
sirv
skuvault
skyvia
slack
slicktext
sling
slite
small-improvements
smartemailing
smarthr
smartlead
smartproxy
smartroutes
smartsheet
smily
smokeball
smol-machines
smoove
sms77
smsapi
smsglobal
smtp2go
smtping
snapchat
snapdocs
sncf
snitcher
snowflake
snyk
social-fetch
socialkit
socket
softr
solcast
sonderplan
soundcloud
soundee
spacebring
specstream
speechmatics
spider
spike
spiro
splitwise
spotify
spotio2
sprig
spruce
spydra
squadcast
squarespace-commerce
stack-exchange
stack-overflow-for-teams
stackitdns
staffbase
starbridge
starton
statsig
statuspage
statuspal
stibee
stigg
stonly
stora
straico
strale
streak
stream-chat
streamtime
stripe
studio-by-ai21-labs
subscriptionflow
sumo-logic
sumoquote
sumup
supabase
supadata
super-dispatch
supercast
superdocu
supermemory
supernormal
superset
superwall
suprsend
sure-send
surecart
surevoip
surf
surveymethods
svix
swaggerhub
swarmsyncai
swidoc
sympla
synap
syncmate-by-assitro
syncro
synthflow-ai
systemeio
table
tableau
taggun
tailscale
taleez
talend
talenthr
talentlms
talkable
talkjs
talkroute
tally
tapfiliate
taplio
tave
tavily
teachable
teamcamp
teamup
teamup-calendar
teamwork
teamwork-desk
telegram
telematicssdk
telnyx
teltel
telzio
templated
templatefox
temporal
tentary
terros
text-request
textcortex
textline
textmagic
thanks-io
the-events-calendar
the-odds-api
thecompaniesapi
thehive
thesportsdb
thinkific
thoughtspot
threads
thrivecart
thunder-compute
ticket-tailor
ticketsource
tidb-cloud
tidely
tidio
tidy
tidycal
tik-hub
tiktok
tiktok-ads
timecamp
timeero
timelinesai
timelink
timely
timerex
timescaledb
timing
tinyfish
tinypages
tinyurl
tisane-labs
tmetric
todoist
tomba
tomtom
toneden
topdesk
total-synergy
touchsms
tovuti
traccar
track-pod
trackabi
trackdesk
trackingmore
trackvia
trail
trakt
translate-com
transloadit
trekksoft
trello
tremendous
trestle
trigger-dev
tripadvisor
tripworks
true-list
truss
trustlayer
tryfundable
turbosmtp
turbot-pipes
turso
twelve-data
twilio
twitter
twittershots
typebot
typecast
typeform
typefully
uberduck
uchat
ulama
unifi
unione
unipile
uniswap-api
universe
unleash
uplisting
upload-post
uploadcare
upstash-vector
uptimecom
uptimerobot
urable
urlscanio
us-global-mail
uscreen
userback
usersnap
v0
vagaro
valuecase
vast-ai
vaultre
vc-deal-flow-signal
vcita
vdocipher
vectara
vendasta
vendschat
vercel-ai-gateway
verifone
vervoe
veryfi
vibe
video
video-db
videoupscaler
vimeo
viral-loops
virtualbadgeio
virtualsms
virtuous-crm
virustotal
visma-eaccounting
visualping
visualstudio
vocal-video
voice-ai
voiceflow
volunteerhub
voluum
voucherify
voyage
vtex
vybit-notifications
wachete
waiverfile
walcu-crm
walletap
wallsio
wati
wayfront
weatherbit
weaviate
webcrawlerapi
webcrm
weber-gesamtausgabe
webex
webflow
webscraper-io
webscraping-ai
websupport
weezevent-da56471
weeztix
weights-and-biases
wellnessliving
wetravel
whatsable-ca185063
whatsapp
wheelbase
when-i-work
whoisfreaks
whop
wikimedia
wild-apricot
wildberries
wildjar
winston-ai
wisboo
wistia
wix
wiza
wodify-core
wolfram-alpha-api
woop-social
woovi
word
wordnik
wordpress
workable
workiz
workos
workramp
workvivo
wowza
writer
xama-hub
xata
xero
ycloud
yelp
yelp-leads
ynab
yodeck
yodlee
youcanbookme
yousearch
youtrack
youtrust
youtube
youtube-transcript
zadarma
zeeg
zeffy
zendesk
zenegy
zeno
zenoti
zenrows
zenzap
zep
zeplin
zigpoll
zoho-books
zoho-cliq
zoho-cpaas-formerly-zeptomail
zoho-creator
zoho-crm
zoho-inventory
zoho-projects
zoho-work-drive
zoho-writer
zonnagps
zoom
zoominfo
zsign
zulip
zuora
zyte-api`.split(/\s+/)
);

/** Of those, the operations NoClick buys from the app's own service on its own key: a call to one says what it
 *  did, never whose service did it. */
export const PLATFORM_VENDOR_OPERATIONS: Record<string, readonly string[]> = {
    "exa": [
        "search",
        "get_contents",
        "answer",
        "find_similar"
    ],
    "perplexity": [
        "chat_completion",
        "search",
        "academic_search",
        "sec_search",
        "structured_output"
    ]
};
