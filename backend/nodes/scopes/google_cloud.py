"""Google Cloud / Workspace-adjacent operation → OAuth scope requirements.

Eleven nodes share one module because they share one vocabulary: every scope below
is a ``https://www.googleapis.com/auth/...`` string, and Google publishes the
accepted scope set per API method in its machine-readable discovery documents
(``https://<api>.googleapis.com/$discovery/rest?version=<v>``). Every entry here
was derived from those documents, cross-checked against
https://developers.google.com/identity/protocols/oauth2/scopes.

Two quirks drive the shape:

- **Google methods accept a SET of alternative scopes**, unlike Slack where a
  method needs one specific scope. ``ScopeRequirement.scopes`` is an AND-list, so
  each entry names the ONE accepted alternative the node actually connects with —
  the least-privileged scope that is both sufficient per the docs and present in
  the node's ``x-oauth-scopes``. Picking a "more correct" alternative the node
  never requests would be a lie about what the credential can do.
- **Gmail's scopes are not a ladder.** ``gmail.modify`` does not imply
  ``gmail.compose``, ``gmail.labels`` covers label CRUD but nothing else, and
  permanent deletion is gated behind the all-or-nothing ``https://mail.google.com/``
  which none of the finer scopes satisfy. Reply/forward need BOTH ``gmail.modify``
  (read the source message) and ``gmail.compose`` (send the new one).

All registries run at ``Enforcement.SUBSET``: the derived union must be covered
by what each node already requests, but the hand-written request lists are left
untouched — Google rejects unknown scopes at the authorize step and a removed
scope silently downgrades every live credential on the next refresh.
"""

from __future__ import annotations

from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement

_G = "https://www.googleapis.com/auth/"


def _s(*scopes: str) -> ScopeRequirement:
    return ScopeRequirement(scopes=tuple(_G + s for s in scopes))


# ---------------------------------------------------------------------------
# Gmail — gmail.googleapis.com/gmail/v1
# ---------------------------------------------------------------------------

# Reads (messages/threads/profile) accept gmail.readonly, which the node does not
# request; gmail.modify is the accepted alternative it does hold.
_GMAIL_READ = _s("gmail.modify")
_GMAIL_WRITE = _s("gmail.modify")
_GMAIL_DRAFT = _s("gmail.compose")
_GMAIL_LABEL = _s("gmail.labels")
# messages.get to build the quote/headers, then messages.send.
_GMAIL_REPLY = _s("gmail.modify", "gmail.compose")

GMAIL_SCOPES = ScopeRegistry(
    provider="gmail",
    requirements={
        # users.messages.*
        "send_email_message": _s("gmail.compose"),  # messages.send
        "fetch_emails_from_inbox": _GMAIL_READ,  # messages.list + messages.get
        "fetch_email_message": _GMAIL_READ,
        "move_message_to_trash": _GMAIL_WRITE,  # messages.trash
        "restore_message_from_trash": _GMAIL_WRITE,  # messages.untrash
        "update_message_labels": _GMAIL_WRITE,  # messages.modify
        "reply_to_email_message": _GMAIL_REPLY,
        "forward_email_message": _GMAIL_REPLY,
        # users.drafts.*
        "create_email_draft": _GMAIL_DRAFT,
        "list_email_drafts": _GMAIL_DRAFT,
        "fetch_email_draft": _GMAIL_DRAFT,
        "update_email_draft": _GMAIL_DRAFT,
        "delete_email_draft": _GMAIL_DRAFT,
        "send_email_draft": _GMAIL_DRAFT,
        # users.labels.* — also served by the label dropdown loader.
        "list_email_labels": _GMAIL_LABEL,
        "create_email_label": _GMAIL_LABEL,
        "fetch_email_label": _GMAIL_LABEL,
        "update_email_label": _GMAIL_LABEL,
        "delete_email_label": _GMAIL_LABEL,
        # users.threads.*
        "list_email_threads": _GMAIL_READ,
        "fetch_email_thread": _GMAIL_READ,
        "move_thread_to_trash": _GMAIL_WRITE,
        "restore_thread_from_trash": _GMAIL_WRITE,
        "update_thread_labels": _GMAIL_WRITE,
        # users.getProfile
        "fetch_user_profile": _GMAIL_READ,
        # Trigger: messages.list + messages.get, then messages.modify to
        # mark-as-read — all covered by gmail.modify.
        "poll_for_new_emails": _GMAIL_WRITE,
    },
    unmapped=(
        # MISSING SCOPE: https://mail.google.com/ — users.messages.delete and
        # users.threads.delete accept NO other scope (gmail.modify is rejected).
        # Requesting it would grant total mailbox access, so the fix is a product
        # decision, not a table edit.
        "permanently_delete_message",
        "permanently_delete_thread",
    ),
)


# ---------------------------------------------------------------------------
# Google Meet — meet.googleapis.com/v2
# ---------------------------------------------------------------------------

# conferenceRecords and its children accept meetings.space.created (spaces the
# app made) or meetings.space.readonly (anything the user can see). The node
# reads records it did not necessarily create, so readonly is the honest one.
_MEET_READ = _s("meetings.space.readonly")
_MEET_OWN = _s("meetings.space.created")

GOOGLE_MEET_SCOPES = ScopeRegistry(
    provider="google-meet",
    requirements={
        "create_space": _MEET_OWN,  # spaces.create
        "end_active_conference": _MEET_OWN,  # spaces.endActiveConference
        # spaces.patch accepts meetings.space.created or .settings; .settings is
        # the one that also works on spaces this app did not create.
        "update_space": _s("meetings.space.settings"),
        "get_space": _MEET_READ,
        "get_conference_record": _MEET_READ,
        "list_conference_records": _MEET_READ,
        "get_participant": _MEET_READ,
        "list_participants": _MEET_READ,
        "get_participant_session": _MEET_READ,
        "list_participant_sessions": _MEET_READ,
        "get_recording": _MEET_READ,
        "list_recordings": _MEET_READ,
        "get_transcript": _MEET_READ,
        "list_transcripts": _MEET_READ,
        "get_transcript_entry": _MEET_READ,
        "list_transcript_entries": _MEET_READ,
        "get_smart_notes": _MEET_READ,
        "list_smart_notes": _MEET_READ,
        "on_new_conference_record": _MEET_READ,  # polls conferenceRecords.list
    },
)


# ---------------------------------------------------------------------------
# Google Translate — translate.googleapis.com/v3 + /language/translate/v2
# ---------------------------------------------------------------------------

# Every v2 and v3 method accepts cloud-translation (or the broader
# cloud-platform, which the node does not request). v2 operations also run on an
# API-key credential, where no scope applies at all.
_TRANSLATE = _s("cloud-translation")

GOOGLE_TRANSLATE_SCOPES = ScopeRegistry(
    provider="google-translate",
    requirements={
        "v2_translate_text": _TRANSLATE,
        "v2_detect_language": _TRANSLATE,
        "v2_list_languages": _TRANSLATE,
        "v3_translate_text": _TRANSLATE,
        "v3_detect_language": _TRANSLATE,
        "v3_supported_languages": _TRANSLATE,
        "v3_romanize_text": _TRANSLATE,
        "v3_translate_document": _TRANSLATE,
        "v3_batch_translate_text": _TRANSLATE,
        "v3_create_glossary": _TRANSLATE,
        "v3_list_glossaries": _TRANSLATE,
        "v3_get_operation": _TRANSLATE,
        "on_batch_completed": _TRANSLATE,  # polls projects.locations.operations.list
    },
)


# ---------------------------------------------------------------------------
# Google Search Console — webmasters/v3 + searchconsole/v1
# ---------------------------------------------------------------------------

# Reads accept webmasters.readonly, which the node does not request; writes
# accept only webmasters. One scope for both keeps the table honest.
_GSC = _s("webmasters")

GOOGLE_SEARCH_CONSOLE_SCOPES = ScopeRegistry(
    provider="google-search-console",
    requirements={
        "list_sites": _GSC,
        "get_site": _GSC,
        "add_site": _GSC,
        "delete_site": _GSC,
        "list_sitemaps": _GSC,
        "get_sitemap": _GSC,
        "submit_sitemap": _GSC,
        "delete_sitemap": _GSC,
        "query_search_analytics": _GSC,
        "inspect_url": _GSC,
        # urlTestingTools.mobileFriendlyTest.run declares no scopes — it is a
        # public testing endpoint that authenticates but authorizes nothing.
        "mobile_friendly_test": ScopeRequirement(
            scopes=(),
            note="Public URL testing endpoint; requires no OAuth scope.",
        ),
    },
)


# ---------------------------------------------------------------------------
# Google Ads — googleads.googleapis.com
# ---------------------------------------------------------------------------

# The Google Ads API has exactly one OAuth scope; every operation is a GAQL
# search against customers/{id}/googleAds:search. Access is additionally gated by
# a developer token, which is not an OAuth concern.
_ADS = _s("adwords")

GOOGLE_ADS_SCOPES = ScopeRegistry(
    provider="google-ads",
    requirements={
        "run_gaql_query": _ADS,
        "get_campaign_performance_metrics": _ADS,
        "get_ad_group_performance_metrics": _ADS,
        "get_keyword_performance_metrics": _ADS,
        "get_search_terms_triggering_ads": _ADS,
    },
)


# ---------------------------------------------------------------------------
# Google Analytics (GA4) — analyticsdata/v1beta + analyticsadmin/v1beta
# ---------------------------------------------------------------------------

# Every operation is a read: the Data API reports accept analytics.readonly, and
# so does accountSummaries.list behind the property dropdown.
_GA = _s("analytics.readonly")

GOOGLE_ANALYTICS_SCOPES = ScopeRegistry(
    provider="google-analytics",
    requirements={
        "run_ga4_standard_report": _GA,  # properties.runReport
        "run_ga4_realtime_report": _GA,  # properties.runRealtimeReport
        "fetch_ga4_dimensions_and_metrics": _GA,  # properties.getMetadata
    },
)


# ---------------------------------------------------------------------------
# Google Business Profile — mybusiness*, businessprofileperformance
# ---------------------------------------------------------------------------

# The Business Profile APIs are split across five hosts but share a single
# scope. Their discovery documents declare no per-method scopes; the scope is
# published on the OAuth scopes reference as "Manage your Business Profile on
# Google".
_GBP = _s("business.manage")

GOOGLE_BUSINESS_PROFILE_SCOPES = ScopeRegistry(
    provider="google-business-profile",
    requirements={
        # mybusinessbusinessinformation/v1
        "list_business_profile_locations": _GBP,
        "get_location": _GBP,
        "update_location": _GBP,
        "get_location_attributes": _GBP,
        "update_location_attributes": _GBP,
        # mybusiness/v4 — reviews
        "list_location_reviews": _GBP,
        "get_review": _GBP,
        "reply_to_review": _GBP,
        "delete_review_reply": _GBP,
        # mybusiness/v4 — local posts
        "list_local_posts": _GBP,
        "get_local_post": _GBP,
        "create_local_post": _GBP,
        "update_local_post": _GBP,
        "delete_local_post": _GBP,
        "get_local_post_insights": _GBP,
        # mybusiness/v4 — media
        "list_media": _GBP,
        "get_media": _GBP,
        "create_media": _GBP,
        "delete_media": _GBP,
        "list_customer_media": _GBP,
        # businessprofileperformance/v1
        "fetch_location_performance_metrics": _GBP,
        "fetch_location_search_keywords": _GBP,
        # mybusinessplaceactions/v1
        "list_place_action_links": _GBP,
        "create_place_action_link": _GBP,
        "update_place_action_link": _GBP,
        "delete_place_action_link": _GBP,
    },
)


# ---------------------------------------------------------------------------
# Google Cloud Storage — storage/v1 (+ /v2 intelligenceConfig)
# ---------------------------------------------------------------------------

# GCS grades its own methods: object/bucket data operations take read_write,
# while anything touching ACLs, IAM policy on a bucket, HMAC keys, or a full
# PUT/PATCH of bucket or object metadata takes full_control. Both are requested,
# so each entry names the lower of the two that the docs actually accept —
# getting this wrong is silent over-privilege, not a runtime failure.
_GCS_RW = _s("devstorage.read_write")
_GCS_FULL = _s("devstorage.full_control")

GOOGLE_CLOUD_STORAGE_SCOPES = ScopeRegistry(
    provider="google-cloud-storage",
    requirements={
        # buckets.*
        "list_buckets": _GCS_RW,
        "get_bucket": _GCS_RW,
        "create_bucket": _GCS_RW,
        "update_bucket": _GCS_FULL,  # buckets.update
        "patch_bucket": _GCS_FULL,  # buckets.patch
        "delete_bucket": _GCS_RW,
        "lock_retention_policy": _GCS_RW,
        "get_storage_layout": _GCS_RW,
        "restore_bucket": _GCS_RW,
        "relocate_bucket": _GCS_RW,
        # buckets.operations.*
        "get_operation": _GCS_RW,
        "list_operations": _GCS_RW,
        "cancel_operation": _GCS_RW,
        "advance_relocate_bucket": _GCS_RW,
        # IAM policy
        "get_bucket_iam": _GCS_FULL,  # buckets.getIamPolicy
        "set_bucket_iam": _GCS_FULL,  # buckets.setIamPolicy
        "test_iam_permissions": _GCS_RW,
        "get_object_iam": _GCS_RW,
        "set_object_iam": _GCS_RW,
        "test_object_iam_permissions": _GCS_RW,
        # objects.*
        "list_objects": _GCS_RW,
        "get_object": _GCS_RW,
        "download_object": _GCS_RW,
        "upload_object": _GCS_RW,
        "update_object": _GCS_FULL,  # objects.update
        "patch_object": _GCS_FULL,  # objects.patch
        "delete_object": _GCS_RW,
        "copy_object": _GCS_RW,
        "rewrite_object": _GCS_RW,
        "move_object": _GCS_RW,
        "compose_objects": _GCS_RW,
        "restore_object": _GCS_FULL,  # objects.restore
        "bulk_restore_objects": _GCS_RW,
        "on_new_object": _GCS_RW,  # polls objects.list
        # bucketAccessControls.* — ACLs are full_control only.
        "list_bucket_acl": _GCS_FULL,
        "get_bucket_acl": _GCS_FULL,
        "create_bucket_acl": _GCS_FULL,
        "update_bucket_acl": _GCS_FULL,
        "patch_bucket_acl": _GCS_FULL,
        "delete_bucket_acl": _GCS_FULL,
        # defaultObjectAccessControls.*
        "list_default_object_acl": _GCS_FULL,
        "get_default_object_acl": _GCS_FULL,
        "create_default_object_acl": _GCS_FULL,
        "update_default_object_acl": _GCS_FULL,
        "patch_default_object_acl": _GCS_FULL,
        "delete_default_object_acl": _GCS_FULL,
        # objectAccessControls.*
        "get_object_acl": _GCS_FULL,
        "list_object_acl_entries": _GCS_FULL,
        "get_object_acl_entry": _GCS_FULL,
        "create_object_acl_entry": _GCS_FULL,
        "update_object_acl_entry": _GCS_FULL,
        "patch_object_acl_entry": _GCS_FULL,
        "delete_object_acl_entry": _GCS_FULL,
        # folders.*
        "create_folder": _GCS_RW,
        "get_folder": _GCS_RW,
        "list_folders": _GCS_RW,
        "delete_folder": _GCS_RW,
        "delete_folder_recursive": _GCS_RW,
        "rename_folder": _GCS_RW,
        # managedFolders.*
        "create_managed_folder": _GCS_RW,
        "get_managed_folder": _GCS_RW,
        "list_managed_folders": _GCS_RW,
        "delete_managed_folder": _GCS_RW,
        "get_managed_folder_iam": _GCS_RW,
        "set_managed_folder_iam": _GCS_FULL,  # managedFolders.setIamPolicy
        "test_managed_folder_iam_permissions": _GCS_RW,
        # anywhereCaches.*
        "create_anywhere_cache": _GCS_RW,
        "get_anywhere_cache": _GCS_RW,
        "list_anywhere_caches": _GCS_RW,
        "update_anywhere_cache": _GCS_RW,
        "pause_anywhere_cache": _GCS_RW,
        "resume_anywhere_cache": _GCS_RW,
        "disable_anywhere_cache": _GCS_RW,
        # notifications.*
        "create_notification": _GCS_RW,
        "get_notification": _GCS_RW,
        "list_notifications": _GCS_RW,
        "delete_notification": _GCS_RW,
        # projects.hmacKeys.* — read_write is NOT accepted except on delete.
        "create_hmac_key": _GCS_FULL,
        "get_hmac_key": _GCS_FULL,
        "list_hmac_keys": _GCS_FULL,
        "update_hmac_key": _GCS_FULL,
        "delete_hmac_key": _GCS_RW,
        # projects.serviceAccount.get
        "get_service_account": _GCS_RW,
        # storage/v2 intelligenceConfig
        "get_project_intelligence_config": _GCS_RW,
        "update_project_intelligence_config": _GCS_RW,
        "get_folder_intelligence_config": _GCS_RW,
        "update_folder_intelligence_config": _GCS_RW,
        "get_organization_intelligence_config": _GCS_RW,
        "update_organization_intelligence_config": _GCS_RW,
    },
)


# ---------------------------------------------------------------------------
# BigQuery — bigquery.googleapis.com/bigquery/v2
# ---------------------------------------------------------------------------

# Every bigquery/v2 method accepts the `bigquery` scope. The narrower
# bigquery.insertdata (tabledata.insertAll only) and cloud-platform are the other
# alternatives; neither is requested, so `bigquery` is the entry everywhere.
_BQ = _s("bigquery")

BIGQUERY_SCOPES = ScopeRegistry(
    provider="bigquery",
    requirements={
        # datasets.*
        "list_datasets": _BQ,
        "get_dataset": _BQ,
        "create_dataset": _BQ,
        "update_dataset": _BQ,
        "patch_dataset": _BQ,
        "delete_dataset": _BQ,
        "undelete_dataset": _BQ,
        # tables.*
        "list_tables": _BQ,
        "get_table": _BQ,
        "create_table": _BQ,
        "update_table": _BQ,
        "patch_table": _BQ,
        "delete_table": _BQ,
        "get_table_iam_policy": _BQ,
        "set_table_iam_policy": _BQ,
        "test_table_iam_permissions": _BQ,
        # tabledata.*
        "list_table_data": _BQ,
        "stream_insert": _BQ,  # tabledata.insertAll
        # jobs.*
        "run_query": _BQ,  # jobs.query
        "insert_job": _BQ,
        "get_job": _BQ,
        "list_jobs": _BQ,
        "cancel_job": _BQ,
        "delete_job": _BQ,
        "get_query_results": _BQ,
        "on_query_results": _BQ,  # polls jobs.query
        # models.*
        "list_models": _BQ,
        "get_model": _BQ,
        "patch_model": _BQ,
        "delete_model": _BQ,
        # routines.*
        "list_routines": _BQ,
        "get_routine": _BQ,
        "create_routine": _BQ,
        "update_routine": _BQ,
        "delete_routine": _BQ,
        # rowAccessPolicies.*
        "list_row_access_policies": _BQ,
        "get_row_access_policy": _BQ,
        # projects.*
        "list_projects": _BQ,
        "get_service_account": _BQ,
    },
)


# ---------------------------------------------------------------------------
# Firestore — firestore.googleapis.com/v1
# ---------------------------------------------------------------------------

# Every firestore/v1 method accepts `datastore` (the alternative being the
# broader cloud-platform, which the node does not request), including the admin
# surfaces: databases, indexes, fields, backups, backup schedules and user creds.
_FS = _s("datastore")

FIRESTORE_SCOPES = ScopeRegistry(
    provider="firestore",
    requirements={
        # documents.*
        "get_document": _FS,
        "list_documents": _FS,
        "create_document": _FS,
        "update_document": _FS,
        "delete_document": _FS,
        "batch_get_documents": _FS,
        "batch_write": _FS,
        "write": _FS,
        "commit": _FS,
        "begin_transaction": _FS,
        "rollback": _FS,
        "run_query": _FS,
        "run_aggregation_query": _FS,
        "partition_query": _FS,
        "list_collection_ids": _FS,
        "listen": _FS,
        "execute_pipeline": _FS,
        "on_document_changed": _FS,  # polls documents.runQuery
        # Arbitrary path against firestore.googleapis.com/v1 — every method on
        # that surface takes `datastore`, so the scope holds regardless of path.
        "custom_api_call": _FS,
        # databases.*
        "create_database": _FS,
        "get_database": _FS,
        "list_databases": _FS,
        "update_database": _FS,
        "delete_database": _FS,
        "clone_database": _FS,
        "restore_database": _FS,
        "export_documents": _FS,
        "import_documents": _FS,
        "bulk_delete_documents": _FS,
        # collectionGroups.indexes.* / .fields.*
        "get_index": _FS,
        "list_indexes": _FS,
        "delete_index": _FS,
        "get_field": _FS,
        "list_fields": _FS,
        "update_field": _FS,
        # backups + schedules
        "get_backup": _FS,
        "list_backups": _FS,
        "delete_backup": _FS,
        "create_backup_schedule": _FS,
        "get_backup_schedule": _FS,
        "list_backup_schedules": _FS,
        "update_backup_schedule": _FS,
        "delete_backup_schedule": _FS,
        # userCreds.*
        "create_user_creds": _FS,
        "get_user_creds": _FS,
        "list_user_creds": _FS,
        "enable_user_creds": _FS,
        "disable_user_creds": _FS,
        "delete_user_creds": _FS,
        "reset_user_creds_password": _FS,
        # operations + locations
        "get_operation": _FS,
        "list_operations": _FS,
        "cancel_operation": _FS,
        "delete_operation": _FS,
        "get_location": _FS,
        "list_locations": _FS,
    },
)


# ---------------------------------------------------------------------------
# Display & Video 360 — displayvideo.googleapis.com/v4 + Bid Manager
# doubleclickbidmanager.googleapis.com/v2
# ---------------------------------------------------------------------------

# Every displayvideo/v4 method the node calls accepts `display-video` (per the
# v4 discovery document, only the users.* surface — not implemented here —
# requires `display-video-user-management`). The Bid Manager reporting API is
# single-scope: every queries/reports method takes `doubleclickbidmanager`,
# which also covers the `on_job_completed` trigger's report-list poll.
_DV = _s("display-video")
_DBM = _s("doubleclickbidmanager")

DV360_SCOPES = ScopeRegistry(
    provider="dv360",
    requirements={
        # advertisers.*
        "list_advertisers": _DV,
        "get_advertiser": _DV,
        "create_advertiser": _DV,
        "update_advertiser": _DV,
        # advertisers.campaigns.*
        "list_campaigns": _DV,
        "get_campaign": _DV,
        "create_campaign": _DV,
        "update_campaign": _DV,
        # advertisers.insertionOrders.*
        "list_insertion_orders": _DV,
        "get_insertion_order": _DV,
        "create_insertion_order": _DV,
        "update_insertion_order": _DV,
        # advertisers.lineItems.*
        "list_line_items": _DV,
        "get_line_item": _DV,
        "create_line_item": _DV,
        "update_line_item": _DV,
        "delete_line_item": _DV,
        "duplicate_line_item": _DV,
        # advertisers.creatives.*
        "list_creatives": _DV,
        "get_creative": _DV,
        "create_creative": _DV,
        "update_creative": _DV,
        "delete_creative": _DV,
        # channels.* (advertiser- or partner-anchored)
        "list_channels": _DV,
        "get_channel": _DV,
        "create_channel": _DV,
        # targeting
        "list_assigned_targeting": _DV,
        "create_assigned_targeting": _DV,
        "search_targeting_options": _DV,
        # firstPartyAndPartnerAudiences.*
        "list_audiences": _DV,
        "edit_customer_match_members": _DV,
        # Bid Manager queries.* / queries.reports.*
        "create_report_query": _DBM,
        "run_report_query": _DBM,
        "list_report_queries": _DBM,
        "get_report_query": _DBM,
        "get_report": _DBM,
        "on_job_completed": _DBM,  # polls queries.reports.list
    },
)
