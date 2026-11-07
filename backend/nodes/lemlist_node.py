"""Lemlist REST API workflow node.

The operation catalog is derived from Lemlist's public OpenAPI reference at
https://developer.lemlist.com/llms.txt. Every documented, distinct method/path
is exposed; request fields come from the corresponding OpenAPI operation.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
import time
from typing import Annotated, Any, Dict, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Discriminator, Field, create_model

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from utils.ssrf import guarded_async_client


API_BASE = "https://api.lemlist.com/api"
_CATALOG = json.loads(r'''{
  "source": "https://developer.lemlist.com/llms.txt",
  "retrieved": "2026-09-29",
  "operations": [
    {
      "name": "create_lead_in_campaign",
      "title": "Create Lead in Campaign",
      "category": "Leads",
      "description": "Creates a new lead and adds it to a specific campaign. Never updates an existing lead.",
      "method": "POST",
      "path": "/campaigns/{campaignId}/leads/",
      "path_params": [
        "campaignId"
      ],
      "query_params": [
        {
          "name": "deduplicate",
          "type": "boolean",
          "required": false,
          "description": "Refuse the lead with `409 LEAD_ALREADY_IN_OTHER_CAMPAIGN` when the contact already has one in another campaign. Default: false. The campaign's own \"remove duplicates\" setting does not apply here."
        },
        {
          "name": "linkedinEnrichment",
          "type": "boolean",
          "required": false,
          "description": "Run the LinkedIn enrichment. Default: false"
        },
        {
          "name": "findEmail",
          "type": "boolean",
          "required": false,
          "description": "Find verified email. Default: false"
        },
        {
          "name": "verifyEmail",
          "type": "boolean",
          "required": false,
          "description": "Verify existing email (debounce). Default: false"
        },
        {
          "name": "findPhone",
          "type": "boolean",
          "required": false,
          "description": "Find phone number. Default: false"
        },
        {
          "name": "updateStrategy",
          "type": "string",
          "required": false,
          "description": "What the matched contact and company keep (the lead is always created). `overwrite` (default): sent values replace stored ones, an empty string clears. `overwriteIgnoreEmpty`: empty values ignored. `fillEmptyOnly`: only empty fields filled, identifiers, links, owner and status kept. Other values: 400."
        }
      ],
      "body_content_type": "application/json",
      "body_required": false,
      "body_properties": [
        {
          "name": "email",
          "type": "string",
          "required": false,
          "description": "Email of the lead"
        },
        {
          "name": "firstName",
          "type": "string",
          "required": false,
          "description": "First name of the lead"
        },
        {
          "name": "lastName",
          "type": "string",
          "required": false,
          "description": "Last name of the lead"
        },
        {
          "name": "companyName",
          "type": "string",
          "required": false,
          "description": "Company name"
        },
        {
          "name": "jobTitle",
          "type": "string",
          "required": false,
          "description": "Job title"
        },
        {
          "name": "linkedinUrl",
          "type": "string",
          "required": false,
          "description": "LinkedIn profile URL"
        },
        {
          "name": "picture",
          "type": "string",
          "required": false,
          "description": "Profile picture URL"
        },
        {
          "name": "phone",
          "type": "string",
          "required": false,
          "description": "Phone number"
        },
        {
          "name": "companyDomain",
          "type": "string",
          "required": false,
          "description": "Company domain"
        },
        {
          "name": "icebreaker",
          "type": "string",
          "required": false,
          "description": "Personalized icebreaker message"
        },
        {
          "name": "timezone",
          "type": "string",
          "required": false,
          "description": "Lead's timezone in IANA format (e.g., Europe/Paris, America/New_York)"
        },
        {
          "name": "contactOwner",
          "type": "string",
          "required": false,
          "description": "Contact owner (user ID or user login email)"
        }
      ],
      "source": "https://developer.lemlist.com/api-reference/endpoints/leads/create-lead-in-campaign.md"
    },
    {
      "name": "enrich_data",
      "title": "Enrich Data",
      "category": "Enrich",
      "description": "Enriches data by finding emails, phone numbers, or LinkedIn information from various inputs.",
      "method": "POST",
      "path": "/enrich",
      "path_params": [],
      "query_params": [
        {
          "name": "findEmail",
          "type": "boolean",
          "required": false,
          "description": "Find verified email"
        },
        {
          "name": "verifyEmail",
          "type": "boolean",
          "required": false,
          "description": "Verify existing email"
        },
        {
          "name": "linkedinEnrichment",
          "type": "boolean",
          "required": false,
          "description": "Run LinkedIn enrichment"
        },
        {
          "name": "email",
          "type": "string",
          "required": false,
          "description": "Email address"
        },
        {
          "name": "linkedinUrl",
          "type": "string",
          "required": false,
          "description": "LinkedIn URL"
        },
        {
          "name": "firstName",
          "type": "string",
          "required": false,
          "description": "First name"
        },
        {
          "name": "lastName",
          "type": "string",
          "required": false,
          "description": "Last name"
        },
        {
          "name": "companyDomain",
          "type": "string",
          "required": false,
          "description": "Company domain"
        },
        {
          "name": "companyName",
          "type": "string",
          "required": false,
          "description": "Company name"
        },
        {
          "name": "jobTitle",
          "type": "string",
          "required": false,
          "description": "Job title of the person. Optional hint that improves the find rate when matching the right person."
        },
        {
          "name": "findPhone",
          "type": "boolean",
          "required": false,
          "description": "Find phone number"
        },
        {
          "name": "webhookUrl",
          "type": "string",
          "required": false,
          "description": "Webhook URL for enrichment events"
        }
      ],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/enrich/enrich-data.md"
    },
    {
      "name": "search_people_database",
      "title": "Search People database",
      "category": "People Database",
      "description": "Searches the people database using filters, keywords, and pagination.",
      "method": "POST",
      "path": "/database/people",
      "path_params": [],
      "query_params": [],
      "body_content_type": "application/json",
      "body_required": false,
      "body_properties": [
        {
          "name": "filters",
          "type": "array",
          "required": false,
          "description": "Array of filters (required)"
        },
        {
          "name": "page",
          "type": "integer",
          "required": false,
          "description": "Page (optional)"
        },
        {
          "name": "size",
          "type": "integer",
          "required": false,
          "description": "Size of the results, number between 1 and 100 (optional)"
        },
        {
          "name": "excludes",
          "type": "array",
          "required": false,
          "description": "Array of properties to exclude from the results (optional)"
        },
        {
          "name": "search",
          "type": "string",
          "required": false,
          "description": "Free-text query across common people fields (e.g., name, title, company, location)"
        }
      ],
      "source": "https://developer.lemlist.com/api-reference/endpoints/people-database/search-people-database.md"
    },
    {
      "name": "add_webhook",
      "title": "Add Webhook",
      "category": "Webhooks",
      "description": "Creates a webhook that receives real-time POST callbacks for selected events.",
      "method": "POST",
      "path": "/hooks",
      "path_params": [],
      "query_params": [
        {
          "name": "campaignId",
          "type": "string",
          "required": false,
          "description": "Webhook for specific campaign"
        },
        {
          "name": "isFirst",
          "type": "boolean",
          "required": false,
          "description": "Webhook for first activity only"
        },
        {
          "name": "zapId",
          "type": "string",
          "required": false,
          "description": "Zapier ID"
        }
      ],
      "body_content_type": "application/json",
      "body_required": false,
      "body_properties": [
        {
          "name": "targetUrl",
          "type": "string",
          "required": true,
          "description": "The URL that will receive webhook POST requests."
        },
        {
          "name": "type",
          "type": "string",
          "required": false,
          "description": "Optional event type to subscribe to. When omitted, all events are sent. See the full categorized list in the endpoint documentation."
        },
        {
          "name": "secret",
          "type": "string",
          "required": false,
          "description": "Optional shared secret. Stored encrypted, never returned by GET, and immutable once set. Sent back to your endpoint as a `secret` field in the body of every webhook call so you can verify the request originated from lemlist."
        }
      ],
      "source": "https://developer.lemlist.com/api-reference/endpoints/webhooks/add-webhook.md"
    },
    {
      "name": "get_lead_by_email",
      "title": "Get Lead by Email",
      "category": "Leads",
      "description": "Retrieves a specific lead by their email address.",
      "method": "GET",
      "path": "/leads/{email}",
      "path_params": [
        "email"
      ],
      "query_params": [
        {
          "name": "version",
          "type": "string",
          "required": false,
          "description": "API version. v2 is the only option"
        }
      ],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/leads/get-lead-by-email.md"
    },
    {
      "name": "get_team",
      "title": "Get Team",
      "category": "Team",
      "description": "Retrieves information about your team.",
      "method": "GET",
      "path": "/team",
      "path_params": [],
      "query_params": [
        {
          "name": "version",
          "type": "string",
          "required": false,
          "description": "Set to `v2` to include the `users` array, listing each team member's `userId`, `name`, `email`, and `role`. This lets you retrieve the team and its members in a single request."
        }
      ],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/team/get-team.md"
    },
    {
      "name": "get_team_senders",
      "title": "Get Team Senders",
      "category": "Team",
      "description": "Retrieves a list of all team members and their associated campaigns.",
      "method": "GET",
      "path": "/team/senders",
      "path_params": [],
      "query_params": [
        {
          "name": "state",
          "type": "string",
          "required": false,
          "description": "Filter by campaign's state (running, paused, draft, ended, archived, errors)"
        }
      ],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/team/get-team-senders.md"
    },
    {
      "name": "get_team_credits",
      "title": "Get Team Credits",
      "category": "Team",
      "description": "Retrieves the remaining credits balance for your team's account.",
      "method": "GET",
      "path": "/team/credits",
      "path_params": [],
      "query_params": [],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/team/get-team-credits.md"
    },
    {
      "name": "get_user",
      "title": "Get User",
      "category": "Users",
      "description": "Retrieves all information for a specific user by their ID.",
      "method": "GET",
      "path": "/users/{userId}",
      "path_params": [
        "userId"
      ],
      "query_params": [],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/users/get-user.md"
    },
    {
      "name": "get_user_channels",
      "title": "Get User Channels",
      "category": "Users",
      "description": "Retrieves the connected channels (email, LinkedIn, WhatsApp) and their availability for the authenticated user.",
      "method": "GET",
      "path": "/user/channels",
      "path_params": [],
      "query_params": [],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/users/get-user-channels.md"
    },
    {
      "name": "connect_email_account",
      "title": "Connect Email Account",
      "category": "Email Accounts",
      "description": "Connects a new SMTP/IMAP email account to your team.",
      "method": "POST",
      "path": "/user/email-accounts",
      "path_params": [],
      "query_params": [],
      "body_content_type": "application/json",
      "body_required": true,
      "body_properties": [
        {
          "name": "sender_name",
          "type": "string",
          "required": true,
          "description": "Display name for the sender."
        },
        {
          "name": "sender_email",
          "type": "string",
          "required": true,
          "description": "Email address used as the sender."
        },
        {
          "name": "smtp_host",
          "type": "string",
          "required": true,
          "description": "SMTP server hostname."
        },
        {
          "name": "smtp_port",
          "type": "integer",
          "required": true,
          "description": "SMTP server port."
        },
        {
          "name": "smtp_login",
          "type": "string",
          "required": true,
          "description": "SMTP authentication login."
        },
        {
          "name": "smtp_password",
          "type": "string",
          "required": true,
          "description": "SMTP authentication password."
        },
        {
          "name": "smtp_secure",
          "type": "boolean",
          "required": false,
          "description": "Use SSL/TLS for SMTP connection."
        },
        {
          "name": "imap_host",
          "type": "string",
          "required": true,
          "description": "IMAP server hostname."
        },
        {
          "name": "imap_port",
          "type": "integer",
          "required": true,
          "description": "IMAP server port."
        },
        {
          "name": "imap_login",
          "type": "string",
          "required": true,
          "description": "IMAP authentication login."
        },
        {
          "name": "imap_password",
          "type": "string",
          "required": true,
          "description": "IMAP authentication password."
        },
        {
          "name": "imap_secure",
          "type": "boolean",
          "required": false,
          "description": "Use SSL/TLS for IMAP connection."
        },
        {
          "name": "userId",
          "type": "string",
          "required": false,
          "description": "Assign the email account to a specific team member. Must be a member of the team. Defaults to the API key creator or team owner."
        }
      ],
      "source": "https://developer.lemlist.com/api-reference/endpoints/email-accounts/connect-email-account.md"
    },
    {
      "name": "disconnect_email_account",
      "title": "Disconnect Email Account",
      "category": "Email Accounts",
      "description": "Disconnects an email account from your team.",
      "method": "DELETE",
      "path": "/user/email-accounts/{emailAccountId}",
      "path_params": [
        "emailAccountId"
      ],
      "query_params": [],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/email-accounts/disconnect-email-account.md"
    },
    {
      "name": "test_email_account",
      "title": "Test Email Account",
      "category": "Email Accounts",
      "description": "Tests the SMTP and IMAP connection of an email account.",
      "method": "POST",
      "path": "/user/email-accounts/{emailAccountId}/test",
      "path_params": [
        "emailAccountId"
      ],
      "query_params": [],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/email-accounts/test-email-account.md"
    },
    {
      "name": "create_campaign",
      "title": "Create Campaign",
      "category": "Campaigns",
      "description": "Creates a new campaign with auto-generated sequence and schedule.",
      "method": "POST",
      "path": "/campaigns",
      "path_params": [],
      "query_params": [],
      "body_content_type": "application/json",
      "body_required": false,
      "body_properties": [
        {
          "name": "name",
          "type": "string",
          "required": true,
          "description": "The name of the campaign"
        },
        {
          "name": "timezone",
          "type": "string",
          "required": false,
          "description": "IANA timezone for the campaign schedule (e.g. `America/New_York`). Defaults to `Europe/Paris` if omitted."
        },
        {
          "name": "autoReview",
          "type": "boolean",
          "required": false,
          "description": "Automatically launch (review) leads as soon as they are added to the campaign, instead of requiring manual review. Defaults to `false`."
        },
        {
          "name": "autoReviewConditions",
          "type": "array",
          "required": false,
          "description": "Email deliverability statuses for which a lead is auto-launched when `autoReview` is enabled. Only leads whose email verification matches one of these statuses are launched automatically. Invalid values are rejected with a `400` error."
        }
      ],
      "source": "https://developer.lemlist.com/api-reference/endpoints/campaigns/create-campaign.md"
    },
    {
      "name": "get_campaign",
      "title": "Get Campaign",
      "category": "Campaigns",
      "description": "Retrieves detailed information about a specific campaign by ID.",
      "method": "GET",
      "path": "/campaigns/{campaignId}",
      "path_params": [
        "campaignId"
      ],
      "query_params": [],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/campaigns/get-campaign.md"
    },
    {
      "name": "get_many_campaigns",
      "title": "Get Many Campaigns",
      "category": "Campaigns",
      "description": "Retrieves a paginated list of all campaigns in your team.",
      "method": "GET",
      "path": "/campaigns",
      "path_params": [],
      "query_params": [
        {
          "name": "offset",
          "type": "integer",
          "required": false,
          "description": "Offset from the start. For pagination."
        },
        {
          "name": "limit",
          "type": "integer",
          "required": false,
          "description": "Number of campaigns to retrieve. Default: 100. Maximum: 100."
        },
        {
          "name": "version",
          "type": "string",
          "required": false,
          "description": "Set to 'v2' to use the latest version"
        },
        {
          "name": "page",
          "type": "integer",
          "required": false,
          "description": "Page number to retrieve"
        },
        {
          "name": "sortBy",
          "type": "string",
          "required": false,
          "description": "The field by which to sort. Currently, only 'createdAt' is supported."
        },
        {
          "name": "sortOrder",
          "type": "string",
          "required": false,
          "description": "The sort direction. Use 'desc' for descending order; any other value (or omission) will sort in ascending order."
        },
        {
          "name": "status",
          "type": "string",
          "required": false,
          "description": "The campaign status. Can be: running, draft, archived, ended, paused, errors. Note: a campaign can be in multiple statuses at one time (e.g., a paused campaign with errors)."
        },
        {
          "name": "createdBy",
          "type": "string",
          "required": false,
          "description": "Filter campaigns by creator user ID (usr_xxx format). Only returns campaigns created by the specified user."
        }
      ],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/campaigns/get-many-campaigns.md"
    },
    {
      "name": "update_campaign",
      "title": "Update Campaign",
      "category": "Campaigns",
      "description": "Updates the settings and configuration of an existing campaign.",
      "method": "PATCH",
      "path": "/campaigns/{campaignId}",
      "path_params": [
        "campaignId"
      ],
      "query_params": [],
      "body_content_type": "application/json",
      "body_required": false,
      "body_properties": [
        {
          "name": "name",
          "type": "string",
          "required": false,
          "description": "The campaign name"
        },
        {
          "name": "stopOnEmailReplied",
          "type": "boolean",
          "required": false,
          "description": "Stop the campaign when a lead replies by email"
        },
        {
          "name": "stopOnMeetingBooked",
          "type": "boolean",
          "required": false,
          "description": "Stop the campaign when a meeting is booked"
        },
        {
          "name": "stopOnLinkClicked",
          "type": "boolean",
          "required": false,
          "description": "Stop the campaign when a link is clicked"
        },
        {
          "name": "leadsPausedByInterest",
          "type": "boolean",
          "required": false,
          "description": "Pause leads based on interest"
        },
        {
          "name": "opportunityReplied",
          "type": "boolean",
          "required": false,
          "description": "Create an opportunity when a lead replies"
        },
        {
          "name": "opportunityClicked",
          "type": "boolean",
          "required": false,
          "description": "Create an opportunity when a lead clicks a link"
        },
        {
          "name": "autoLeadInterest",
          "type": "boolean",
          "required": false,
          "description": "Automatically detect lead interest"
        },
        {
          "name": "disableTrackOpen",
          "type": "boolean",
          "required": false,
          "description": "Disable tracking of email opens"
        },
        {
          "name": "disableTrackClick",
          "type": "boolean",
          "required": false,
          "description": "Disable tracking of link clicks"
        },
        {
          "name": "disableTrackReply",
          "type": "boolean",
          "required": false,
          "description": "Disable tracking of email replies"
        },
        {
          "name": "disableOutOfOffice",
          "type": "boolean",
          "required": false,
          "description": "Disable out-of-office detection"
        },
        {
          "name": "sequenceSharing",
          "type": "boolean",
          "required": false,
          "description": "Enable sequence sharing for the campaign"
        },
        {
          "name": "stopOnLinkClickedFilter",
          "type": "string",
          "required": false,
          "description": "Filter for which link clicks should stop the campaign"
        },
        {
          "name": "sendUserIds",
          "type": "array",
          "required": false,
          "description": "Array of user IDs (usr_xxx format) to assign as campaign senders. Cannot be used on campaigns with a dynamic sender strategy (contactOwner, leadImporter, customField). Each sender is validated against the campaign's sending channels (email, LinkedIn, SMS, WhatsApp): senders without capabilities for at least one channel are excluded, and all channels must be covered by at least one sender."
        },
        {
          "name": "autoReview",
          "type": "boolean",
          "required": false,
          "description": "Automatically launch (review) leads as soon as they are added to the campaign, instead of requiring manual review."
        },
        {
          "name": "autoReviewConditions",
          "type": "array",
          "required": false,
          "description": "Email deliverability statuses for which a lead is auto-launched when `autoReview` is enabled. Only leads whose email verification matches one of these statuses are launched automatically. Invalid values are rejected with a `400` error."
        },
        {
          "name": "aiFeatures",
          "type": "object",
          "required": false,
          "description": "AI reply-handling settings. Provide only the flags to change; omitted flags keep their current value."
        },
        {
          "name": "tracking",
          "type": "object",
          "required": false,
          "description": "Open / click / reply tracking toggles."
        },
        {
          "name": "onReplied",
          "type": "object",
          "required": false,
          "description": "Behavior when a lead replies."
        },
        {
          "name": "onLinkClicked",
          "type": "object",
          "required": false,
          "description": "Behavior when a lead clicks a tracked link."
        },
        {
          "name": "onMeetingBooked",
          "type": "object",
          "required": false,
          "description": "Behavior when a meeting is booked."
        }
      ],
      "source": "https://developer.lemlist.com/api-reference/endpoints/campaigns/update-campaign.md"
    },
    {
      "name": "get_campaign_statutes",
      "title": "Get Campaign Statutes",
      "category": "Campaigns",
      "description": "Retrieves validation statutes for a campaign, including errors that block launching and warnings about daily limits, DNS issues, etc.",
      "method": "GET",
      "path": "/campaigns/{campaignId}/statutes",
      "path_params": [
        "campaignId"
      ],
      "query_params": [],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/campaigns/get-campaign-statutes.md"
    },
    {
      "name": "start_campaign",
      "title": "Start Campaign",
      "category": "Campaigns",
      "description": "Starts or resumes a paused campaign.",
      "method": "POST",
      "path": "/campaigns/{campaignId}/start",
      "path_params": [
        "campaignId"
      ],
      "query_params": [],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/campaigns/start-campaign.md"
    },
    {
      "name": "pause_campaign",
      "title": "Pause Campaign",
      "category": "Campaigns",
      "description": "Pauses a running campaign without affecting scheduled leads.",
      "method": "POST",
      "path": "/campaigns/{campaignId}/pause",
      "path_params": [
        "campaignId"
      ],
      "query_params": [],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/campaigns/pause-campaign.md"
    },
    {
      "name": "skip_step_for_everyone",
      "title": "Skip Step for Everyone",
      "category": "Campaigns",
      "description": "Skips one step of a running campaign for every lead.",
      "method": "POST",
      "path": "/campaigns/{campaignId}/steps/{stepId}/skip",
      "path_params": [
        "campaignId",
        "stepId"
      ],
      "query_params": [],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/campaigns/skip-step-for-everyone.md"
    },
    {
      "name": "duplicate_campaign",
      "title": "Duplicate Campaign",
      "category": "Campaigns",
      "description": "Duplicates an existing campaign with all its sequences, schedules, and templates.",
      "method": "POST",
      "path": "/campaigns/{campaignId}/duplicate",
      "path_params": [
        "campaignId"
      ],
      "query_params": [],
      "body_content_type": "application/json",
      "body_required": false,
      "body_properties": [
        {
          "name": "name",
          "type": "string",
          "required": false,
          "description": "Custom name for the duplicated campaign. If not provided, the original name with ' Copy' suffix is used."
        }
      ],
      "source": "https://developer.lemlist.com/api-reference/endpoints/campaigns/duplicate-campaign.md"
    },
    {
      "name": "get_campaign_stats",
      "title": "Get Campaign Stats",
      "category": "Campaigns",
      "description": "Retrieves performance statistics for a specific campaign.",
      "method": "GET",
      "path": "/v2/campaigns/{campaignId}/stats",
      "path_params": [
        "campaignId"
      ],
      "query_params": [
        {
          "name": "startDate",
          "type": "string",
          "required": true,
          "description": "Start date in ISO 8601 format"
        },
        {
          "name": "endDate",
          "type": "string",
          "required": true,
          "description": "End date in ISO 8601 format"
        },
        {
          "name": "sendUser",
          "type": "string",
          "required": false,
          "description": "Filter stats by send user. Format: `sendUserId|sendUserEmail`. The sendUserId should begin with 'usr_' and the sendUserEmail should be a valid sender email. If the param is specified, both sendUserId and sendUserEmail are mandatory."
        },
        {
          "name": "ABSelected",
          "type": "string",
          "required": false,
          "description": "A/B version filter"
        },
        {
          "name": "channels",
          "type": "string",
          "required": false,
          "description": "JSON array of channels to include. Possible values: 'email', 'linkedin', 'others'"
        }
      ],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/campaigns/get-campaign-stats.md"
    },
    {
      "name": "get_batch_campaign_stats",
      "title": "Get Batch Campaign Stats",
      "category": "Campaigns",
      "description": "Retrieves performance statistics for multiple campaigns in a single request.",
      "method": "POST",
      "path": "/v2/campaigns/stats/batch",
      "path_params": [],
      "query_params": [],
      "body_content_type": "application/json",
      "body_required": true,
      "body_properties": [
        {
          "name": "campaignIds",
          "type": "array",
          "required": true,
          "description": "Array of campaign IDs to retrieve stats for"
        },
        {
          "name": "startDate",
          "type": "string",
          "required": true,
          "description": "Start date in ISO 8601 format"
        },
        {
          "name": "endDate",
          "type": "string",
          "required": true,
          "description": "End date in ISO 8601 format"
        },
        {
          "name": "sendUser",
          "type": "string",
          "required": false,
          "description": "Filter stats by send user. Format: `sendUserId|sendUserEmail`. The sendUserId should begin with 'usr_' and the sendUserEmail should be a valid sender email. If the param is specified, both sendUserId and sendUserEmail are mandatory."
        },
        {
          "name": "ABSelected",
          "type": "string",
          "required": false,
          "description": "A/B version filter"
        },
        {
          "name": "channels",
          "type": "array",
          "required": false,
          "description": "Filter by communication channels"
        }
      ],
      "source": "https://developer.lemlist.com/api-reference/endpoints/campaigns/get-batch-campaign-stats.md"
    },
    {
      "name": "start_campaign_stats_export",
      "title": "Start Campaign Stats Export",
      "category": "Campaigns",
      "description": "Initiates an asynchronous export of campaign statistics to a CSV file.",
      "method": "GET",
      "path": "/campaigns/{campaignId}/export/start",
      "path_params": [
        "campaignId"
      ],
      "query_params": [],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/campaigns/start-campaign-export.md"
    },
    {
      "name": "get_campaign_export_status",
      "title": "Get Campaign Export Status",
      "category": "Campaigns",
      "description": "Checks the status of an asynchronous campaign export.",
      "method": "GET",
      "path": "/campaigns/{campaignId}/export/{exportId}/status",
      "path_params": [
        "campaignId",
        "exportId"
      ],
      "query_params": [],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/campaigns/get-campaign-export-status.md"
    },
    {
      "name": "set_email_for_campaign_export_notification",
      "title": "Set Email for Campaign Export Notification",
      "category": "Campaigns",
      "description": "Configures email notification delivery when a campaign export completes.",
      "method": "PUT",
      "path": "/campaigns/{campaignId}/export/{exportId}/email/{email}",
      "path_params": [
        "campaignId",
        "exportId",
        "email"
      ],
      "query_params": [],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/campaigns/set-export-email-notification.md"
    },
    {
      "name": "export_campaign_leads",
      "title": "Export Campaign Leads",
      "category": "Campaigns",
      "description": "Exports leads from a campaign with flexible filtering and format options.",
      "method": "GET",
      "path": "/v2/campaigns/{campaignId}/export/leads",
      "path_params": [
        "campaignId"
      ],
      "query_params": [
        {
          "name": "state",
          "type": "string",
          "required": false,
          "description": "Filter to export only the specified lead's last states. Use 'all' to export all states. Can be a comma-separated list of states. **Global states**: imported, scanned, skipped, reviewed, contacted, hooked, attracted, warmed, interested, notInterested, emailsBounced, emailsUnsubscribed, failed, meetingBooked, paused. **Detailed states**: emailsSent, emailsOpened, emailsClicked, emailsReplied, emailsInterested, emailsNotInterested, emailsFailed, opportunitiesDone, aircallDone, aircallInterested, ai"
        },
        {
          "name": "format",
          "type": "string",
          "required": false,
          "description": "Output format: 'json' or 'csv'. Default is CSV."
        }
      ],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/campaigns/export-campaign-leads-v2.md"
    },
    {
      "name": "export_campaign_leads_legacy",
      "title": "Export Campaign Leads (legacy)",
      "category": "Campaigns",
      "description": "Exports leads from a campaign with flexible filtering and format options.",
      "method": "GET",
      "path": "/campaigns/{campaignId}/export/leads",
      "path_params": [
        "campaignId"
      ],
      "query_params": [
        {
          "name": "state",
          "type": "string",
          "required": false,
          "description": "Filter to export only the specified lead's last states. Use 'all' to export all states. Can be a comma-separated list of states. **Global states**: imported, scanned, skipped, reviewed, contacted, hooked, attracted, warmed, interested, notInterested, emailsBounced, emailsUnsubscribed, failed, meetingBooked, paused. **Detailed states**: emailsSent, emailsOpened, emailsClicked, emailsReplied, emailsInterested, emailsNotInterested, emailsFailed, opportunitiesDone, aircallDone, aircallInterested, ai"
        },
        {
          "name": "format",
          "type": "string",
          "required": false,
          "description": "Output format: 'json' or 'csv'. Default is CSV."
        }
      ],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/campaigns/export-campaign-leads.md"
    },
    {
      "name": "get_campaign_reports",
      "title": "Get Campaign Reports",
      "category": "Campaigns",
      "description": "Retrieves aggregated reports and statistics for one or multiple campaigns.",
      "method": "GET",
      "path": "/campaigns/reports",
      "path_params": [],
      "query_params": [
        {
          "name": "campaignIds",
          "type": "string",
          "required": true,
          "description": "Comma-separated list of campaign IDs to retrieve reports for"
        }
      ],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/campaigns/get-campaign-reports.md"
    },
    {
      "name": "get_campaign_sequences",
      "title": "Get Campaign Sequences",
      "category": "Sequences",
      "description": "Retrieves all sequences and their steps for a specific campaign.",
      "method": "GET",
      "path": "/campaigns/{campaignId}/sequences",
      "path_params": [
        "campaignId"
      ],
      "query_params": [],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/sequences/get-campaign-sequences.md"
    },
    {
      "name": "add_step_to_sequence",
      "title": "Add Step to Sequence",
      "category": "Sequences",
      "description": "Creates a step or condition within a campaign sequence.",
      "method": "POST",
      "path": "/sequences/{sequenceId}/steps",
      "path_params": [
        "sequenceId"
      ],
      "query_params": [],
      "body_content_type": "application/json",
      "body_required": false,
      "body_properties": [
        {
          "name": "type",
          "type": "string",
          "required": false,
          "description": "The type of step to create"
        },
        {
          "name": "index",
          "type": "integer",
          "required": false,
          "description": "The position within the sequence to insert the new step (≥ -1). If omitted or greater than the number of steps, the new step is added to the end. On a campaign leads have entered, a step inserted before an existing one moves the leads waiting on that step onto the new one; leads already past that position never receive it. Teams without live campaign editing can only append once leads have entered, and a non-tail `index` is refused with `409 SEQUENCE_STEP_INSERT_ON_SEQUENCE_IN_USE`"
        },
        {
          "name": "delay",
          "type": "integer",
          "required": false,
          "description": "Delay in days before executing this step. Defaults to 0 for the first step and 1 for subsequent steps"
        },
        {
          "name": "subject",
          "type": "string",
          "required": false,
          "description": "Email subject line (for email steps). Optional: omit it or send an empty string on a follow-up so the email replies in the thread of the previous one. If no email has been sent to the lead in this campaign yet, it goes out with an empty subject."
        },
        {
          "name": "message",
          "type": "string",
          "required": false,
          "description": "Content of the email or message (used for email, linkedinInvite, linkedinSend, manual, phone, whatsappMessage, sms steps, and as the AI script of a linkedinVoiceNote step in `ai` record mode). Required for linkedinSend, whatsappMessage, and sms"
        },
        {
          "name": "altMessage",
          "type": "string",
          "required": false,
          "description": "The LinkedIn note sent instead of `message` in specific cases, with a meaning that depends on the step type. On `linkedinInvite`: the premium invitation note attached to the connection request, used when the sending account has LinkedIn Premium. On `linkedinSend` and `linkedinVoiceNote`: the out-of-network note, sent as a connection request when the lead is not a 1st-degree connection. Rejected with `400` on any other step type. LinkedIn caps a connection-request note at 200 characters on a free"
        },
        {
          "name": "altMessagePremium",
          "type": "string",
          "required": false,
          "description": "For `linkedinSend` steps only. The premium variant of the out-of-network note, sent instead of `altMessage` when the sending LinkedIn account is Premium or Sales Navigator (300-character LinkedIn cap). Rejected with `400` on any other step type"
        },
        {
          "name": "title",
          "type": "string",
          "required": false,
          "description": "Title or label for manual steps"
        },
        {
          "name": "method",
          "type": "string",
          "required": false,
          "description": "HTTP method for API steps"
        },
        {
          "name": "url",
          "type": "string",
          "required": false,
          "description": "URL of the API endpoint to call (required for api steps). Must start with http:// or https://"
        },
        {
          "name": "conditionKey",
          "type": "string",
          "required": false,
          "description": "Condition key for conditional steps"
        },
        {
          "name": "delayType",
          "type": "string",
          "required": false,
          "description": "Delay type for conditional steps"
        },
        {
          "name": "customField",
          "type": "string",
          "required": false,
          "description": "For conditional steps keyed `customLeadInfo` only. The field to test. A bare name reads as a lead variable (`jobTitle` becomes `variables.jobTitle`); prefix with `fields.` to test a contact field. `$` and the reserved keys `_id`, `teamId`, `campaignId`, `leadId`, `__proto__`, `constructor` and `prototype` are refused."
        },
        {
          "name": "customOperator",
          "type": "string",
          "required": false,
          "description": "For conditional steps keyed `customLeadInfo` only. How the field is compared."
        },
        {
          "name": "customValue",
          "type": "string",
          "required": false,
          "description": "For conditional steps keyed `customLeadInfo` only. The value the field is compared to. Required for `equal` and `contains`, and refused for `empty` and `notEmpty`."
        },
        {
          "name": "campaignId",
          "type": "string",
          "required": false,
          "description": "Target campaign ID for sendToAnotherCampaign steps. The campaign must exist and not be archived"
        },
        {
          "name": "leadAction",
          "type": "string",
          "required": false,
          "description": "Applies to `sendToAnotherCampaign` steps only. What happens to the lead in the SOURCE campaign once it has been moved to the target one. `continue` keeps it running the remaining steps, `pause` pauses it, `stop` ends the source campaign for it. Omitted leaves the step without a value, which behaves as `continue`; a step added from the lemlist UI defaults to `stop`. A transfer that fails always pauses the lead, whatever this says."
        },
        {
          "name": "images",
          "type": "array",
          "required": false,
          "description": "Public HTTPS URLs of images to attach to a `linkedinInvite` or `linkedinSend` step. lemlist downloads each file and re-hosts it. Allowed MIME types: `image/png`, `image/jpeg`, `image/gif`. Up to 20 MB per file, and up to 6 items total combined with `videos`."
        },
        {
          "name": "videos",
          "type": "array",
          "required": false,
          "description": "Public HTTPS URLs of videos to attach to a `linkedinInvite` or `linkedinSend` step. lemlist downloads each file and re-hosts it. Allowed MIME types: `video/mp4`, `video/quicktime`. Up to 20 MB per file, and up to 6 items total combined with `images`."
        },
        {
          "name": "skillName",
          "type": "string",
          "required": false,
          "description": "Name of the LinkedIn skill to endorse on the lead's profile. Applies to `linkedinEndorse` steps only."
        },
        {
          "name": "endorseAnyFallback",
          "type": "boolean",
          "required": false,
          "description": "Applies to `linkedinEndorse` steps only. When `true` and the named skill is not on the lead's profile, lemlist falls back to endorsing any available skill."
        },
        {
          "name": "recordMode",
          "type": "string",
          "required": false,
          "description": "Applies to `linkedinVoiceNote` steps only. Determines how the audio is sourced. `manual` (default) means the user records the audio themselves from the lemlist UI after step creation; `ai` means lemlist generates the audio from a text template provided in the lemlist UI."
        }
      ],
      "source": "https://developer.lemlist.com/api-reference/endpoints/sequences/add-step-to-sequence.md"
    },
    {
      "name": "update_sequence_step",
      "title": "Update Sequence Step",
      "category": "Sequences",
      "description": "Updates an existing step within a sequence.",
      "method": "PATCH",
      "path": "/sequences/{sequenceId}/steps/{stepId}",
      "path_params": [
        "sequenceId",
        "stepId"
      ],
      "query_params": [],
      "body_content_type": "application/json",
      "body_required": false,
      "body_properties": [
        {
          "name": "type",
          "type": "string",
          "required": true,
          "description": "The type of step (required but cannot be changed - must match the existing step type)"
        },
        {
          "name": "delay",
          "type": "integer",
          "required": false,
          "description": "Delay in days before executing this step"
        },
        {
          "name": "subject",
          "type": "string",
          "required": false,
          "description": "Email subject line (for email steps). Pass an empty string to remove it: the email then replies in the thread of the previous email sent to the lead in this campaign."
        },
        {
          "name": "message",
          "type": "string",
          "required": false,
          "description": "Content of the email or message (for email, linkedinInvite, linkedinSend, manual, phone, whatsappMessage, sms steps, and as the AI script of a linkedinVoiceNote step in `ai` record mode)"
        },
        {
          "name": "altMessage",
          "type": "string",
          "required": false,
          "description": "The LinkedIn note sent instead of `message` in specific cases, with a meaning that depends on the step type. On `linkedinInvite`: the premium invitation note attached to the connection request, used when the sending account has LinkedIn Premium. On `linkedinSend` and `linkedinVoiceNote`: the out-of-network note, sent as a connection request when the lead is not a 1st-degree connection. Pass an empty string to clear it. LinkedIn caps a connection-request note at 200 characters on a free account a"
        },
        {
          "name": "altMessagePremium",
          "type": "string",
          "required": false,
          "description": "For `linkedinSend` steps only. The premium variant of the out-of-network note, sent instead of `altMessage` when the sending LinkedIn account is Premium or Sales Navigator (300-character LinkedIn cap). Pass an empty string to clear it. Rejected with `400` on any other step type"
        },
        {
          "name": "title",
          "type": "string",
          "required": false,
          "description": "Title or label for manual steps"
        },
        {
          "name": "method",
          "type": "string",
          "required": false,
          "description": "HTTP method for API steps"
        },
        {
          "name": "url",
          "type": "string",
          "required": false,
          "description": "URL of the API endpoint to call (for api steps). Must start with http:// or https://"
        },
        {
          "name": "conditionKey",
          "type": "string",
          "required": false,
          "description": "Condition key for conditional steps"
        },
        {
          "name": "delayType",
          "type": "string",
          "required": false,
          "description": "Delay type for conditional steps"
        },
        {
          "name": "customField",
          "type": "string",
          "required": false,
          "description": "For conditional steps keyed `customLeadInfo` only. The field to test. A bare name reads as a lead variable (`jobTitle` becomes `variables.jobTitle`); prefix with `fields.` to test a contact field. `$` and the reserved keys `_id`, `teamId`, `campaignId`, `leadId`, `__proto__`, `constructor` and `prototype` are refused."
        },
        {
          "name": "customOperator",
          "type": "string",
          "required": false,
          "description": "For conditional steps keyed `customLeadInfo` only. How the field is compared."
        },
        {
          "name": "customValue",
          "type": "string",
          "required": false,
          "description": "For conditional steps keyed `customLeadInfo` only. The value the field is compared to. Required for `equal` and `contains`, and refused for `empty` and `notEmpty`."
        },
        {
          "name": "campaignId",
          "type": "string",
          "required": false,
          "description": "Target campaign ID for sendToAnotherCampaign steps. The campaign must exist and not be archived"
        },
        {
          "name": "leadAction",
          "type": "string",
          "required": false,
          "description": "Applies to `sendToAnotherCampaign` steps only. What happens to the lead in the SOURCE campaign once it has been moved to the target one. `continue` keeps it running the remaining steps, `pause` pauses it, `stop` ends the source campaign for it. Omitted leaves the step without a value, which behaves as `continue`; a step added from the lemlist UI defaults to `stop`. A transfer that fails always pauses the lead, whatever this says."
        },
        {
          "name": "images",
          "type": "array",
          "required": false,
          "description": "Public HTTPS URLs of images to attach to a `linkedinInvite` or `linkedinSend` step. Replaces the step's current images — pass an empty array to clear them. Allowed MIME types: `image/png`, `image/jpeg`, `image/gif`. Up to 20 MB per file, and up to 6 items total combined with `videos`."
        },
        {
          "name": "videos",
          "type": "array",
          "required": false,
          "description": "Public HTTPS URLs of videos to attach to a `linkedinInvite` or `linkedinSend` step. Replaces the step's current videos — pass an empty array to clear them. Allowed MIME types: `video/mp4`, `video/quicktime`. Up to 20 MB per file, and up to 6 items total combined with `images`."
        },
        {
          "name": "skillName",
          "type": "string",
          "required": false,
          "description": "Name of the LinkedIn skill to endorse on the lead's profile. Applies to `linkedinEndorse` steps only."
        },
        {
          "name": "endorseAnyFallback",
          "type": "boolean",
          "required": false,
          "description": "Applies to `linkedinEndorse` steps only. When `true` and the named skill is not on the lead's profile, lemlist falls back to endorsing any available skill."
        },
        {
          "name": "recordMode",
          "type": "string",
          "required": false,
          "description": "Applies to `linkedinVoiceNote` steps only. Determines how the audio is sourced. `manual` (default) means the user records the audio themselves from the lemlist UI after step creation; `ai` means lemlist generates the audio from a text template provided in the lemlist UI."
        }
      ],
      "source": "https://developer.lemlist.com/api-reference/endpoints/sequences/update-sequence-step.md"
    },
    {
      "name": "delete_sequence_step",
      "title": "Delete Sequence Step",
      "category": "Sequences",
      "description": "Deletes a specific step from a sequence.",
      "method": "DELETE",
      "path": "/sequences/{sequenceId}/steps/{stepId}",
      "path_params": [
        "sequenceId",
        "stepId"
      ],
      "query_params": [],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/sequences/delete-sequence-step.md"
    },
    {
      "name": "list_condition_branches",
      "title": "List Condition Branches",
      "category": "Sequences",
      "description": "Lists the branches of a condition step, in execution order.",
      "method": "GET",
      "path": "/sequences/{sequenceId}/steps/{stepId}/branches",
      "path_params": [
        "sequenceId",
        "stepId"
      ],
      "query_params": [],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/sequences/list-condition-branches.md"
    },
    {
      "name": "add_condition_branch",
      "title": "Add Condition Branch",
      "category": "Sequences",
      "description": "Adds a branch to a condition step and returns it.",
      "method": "POST",
      "path": "/sequences/{sequenceId}/steps/{stepId}/branches",
      "path_params": [
        "sequenceId",
        "stepId"
      ],
      "query_params": [],
      "body_content_type": "application/json",
      "body_required": false,
      "body_properties": [
        {
          "name": "name",
          "type": "string",
          "required": false,
          "description": "The branch's display name. An empty string clears it, and lemlist falls back to labelling the branch \"Branch 1\", \"Branch 2\", … by rank. The Else branch cannot be named."
        },
        {
          "name": "delayType",
          "type": "string",
          "required": false,
          "description": "How a lead-action condition waits: `within` branches once the `delay` window is over, `waitUntil` parks the lead until the action happens, with no time bound. Ignored by the conditions that store no time window (`customLeadInfo`, `hasEmailAddress`)."
        },
        {
          "name": "delay",
          "type": "integer",
          "required": false,
          "description": "Length of that time window, in days."
        },
        {
          "name": "scoreComparator",
          "type": "string",
          "required": false,
          "description": "`hasScore` only - how the lead's score is compared to `scoreThreshold`."
        },
        {
          "name": "scoreThreshold",
          "type": "integer",
          "required": false,
          "description": "`hasScore` only - the score this branch tests against."
        },
        {
          "name": "emailStatusFilter",
          "type": "array",
          "required": false,
          "description": "`hasEmailAddress` only - the email statuses this branch matches. Required to add a branch on that condition."
        },
        {
          "name": "callStatusFilter",
          "type": "array",
          "required": false,
          "description": "`aircallDone` only - the call-status keys this branch matches. The keys are the team's own (defaults plus custom dispositions), so any non-empty string is accepted. Required to add a branch on that condition."
        },
        {
          "name": "customField",
          "type": "string",
          "required": false,
          "description": "`customLeadInfo` only - the field to test. A bare name reads as a lead variable (`jobTitle` becomes `variables.jobTitle`); prefix with `fields.` to test a contact field. Every branch of a step tests the same field, so changing it here changes it on all of them."
        },
        {
          "name": "customOperator",
          "type": "string",
          "required": false,
          "description": "`customLeadInfo` only - how the field is compared. `equal` and `contains` need a `customValue`; `empty` and `notEmpty` refuse one."
        },
        {
          "name": "customValue",
          "type": "string",
          "required": false,
          "description": "`customLeadInfo` only - the value the field is compared to. Required for `equal` and `contains`, and refused for `empty` and `notEmpty`."
        }
      ],
      "source": "https://developer.lemlist.com/api-reference/endpoints/sequences/add-condition-branch.md"
    },
    {
      "name": "reorder_condition_branches",
      "title": "Reorder Condition Branches",
      "category": "Sequences",
      "description": "Rewrites the execution priority of a condition step's branches.",
      "method": "PATCH",
      "path": "/sequences/{sequenceId}/steps/{stepId}/branches",
      "path_params": [
        "sequenceId",
        "stepId"
      ],
      "query_params": [],
      "body_content_type": "application/json",
      "body_required": false,
      "body_properties": [
        {
          "name": "order",
          "type": "array",
          "required": true,
          "description": "Every branch of the step by `sequenceId`, in the new execution order, excluding the Else branch."
        }
      ],
      "source": "https://developer.lemlist.com/api-reference/endpoints/sequences/reorder-condition-branches.md"
    },
    {
      "name": "update_condition_branch",
      "title": "Update Condition Branch",
      "category": "Sequences",
      "description": "Renames a branch and/or changes what it tests.",
      "method": "PATCH",
      "path": "/sequences/{sequenceId}/steps/{stepId}/branches/{branchSequenceId}",
      "path_params": [
        "sequenceId",
        "stepId",
        "branchSequenceId"
      ],
      "query_params": [],
      "body_content_type": "application/json",
      "body_required": false,
      "body_properties": [
        {
          "name": "name",
          "type": "string",
          "required": false,
          "description": "The branch's display name. An empty string clears it, and lemlist falls back to labelling the branch \"Branch 1\", \"Branch 2\", … by rank. The Else branch cannot be named."
        },
        {
          "name": "delayType",
          "type": "string",
          "required": false,
          "description": "How a lead-action condition waits: `within` branches once the `delay` window is over, `waitUntil` parks the lead until the action happens, with no time bound. Ignored by the conditions that store no time window (`customLeadInfo`, `hasEmailAddress`)."
        },
        {
          "name": "delay",
          "type": "integer",
          "required": false,
          "description": "Length of that time window, in days."
        },
        {
          "name": "scoreComparator",
          "type": "string",
          "required": false,
          "description": "`hasScore` only - how the lead's score is compared to `scoreThreshold`."
        },
        {
          "name": "scoreThreshold",
          "type": "integer",
          "required": false,
          "description": "`hasScore` only - the score this branch tests against."
        },
        {
          "name": "emailStatusFilter",
          "type": "array",
          "required": false,
          "description": "`hasEmailAddress` only - the email statuses this branch matches. Required to add a branch on that condition."
        },
        {
          "name": "callStatusFilter",
          "type": "array",
          "required": false,
          "description": "`aircallDone` only - the call-status keys this branch matches. The keys are the team's own (defaults plus custom dispositions), so any non-empty string is accepted. Required to add a branch on that condition."
        },
        {
          "name": "customField",
          "type": "string",
          "required": false,
          "description": "`customLeadInfo` only - the field to test. A bare name reads as a lead variable (`jobTitle` becomes `variables.jobTitle`); prefix with `fields.` to test a contact field. Every branch of a step tests the same field, so changing it here changes it on all of them."
        },
        {
          "name": "customOperator",
          "type": "string",
          "required": false,
          "description": "`customLeadInfo` only - how the field is compared. `equal` and `contains` need a `customValue`; `empty` and `notEmpty` refuse one."
        },
        {
          "name": "customValue",
          "type": "string",
          "required": false,
          "description": "`customLeadInfo` only - the value the field is compared to. Required for `equal` and `contains`, and refused for `empty` and `notEmpty`."
        }
      ],
      "source": "https://developer.lemlist.com/api-reference/endpoints/sequences/update-condition-branch.md"
    },
    {
      "name": "delete_condition_branch",
      "title": "Delete Condition Branch",
      "category": "Sequences",
      "description": "Removes a branch and the sub-tree behind it.",
      "method": "DELETE",
      "path": "/sequences/{sequenceId}/steps/{stepId}/branches/{branchSequenceId}",
      "path_params": [
        "sequenceId",
        "stepId",
        "branchSequenceId"
      ],
      "query_params": [],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/sequences/delete-condition-branch.md"
    },
    {
      "name": "create_a_b_test_variant",
      "title": "Create A/B Test Variant",
      "category": "Sequences",
      "description": "Creates variant B of an A/B test on a step, prefilled from variant A.",
      "method": "POST",
      "path": "/sequences/{sequenceId}/steps/{stepId}/ab-test",
      "path_params": [
        "sequenceId",
        "stepId"
      ],
      "query_params": [],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/sequences/create-ab-test-variant.md"
    },
    {
      "name": "get_a_b_test_variant",
      "title": "Get A/B Test Variant",
      "category": "Sequences",
      "description": "Returns variant B (subject, content, config) of the A/B test on a step.",
      "method": "GET",
      "path": "/sequences/{sequenceId}/steps/{stepId}/ab-test",
      "path_params": [
        "sequenceId",
        "stepId"
      ],
      "query_params": [],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/sequences/get-ab-test-variant.md"
    },
    {
      "name": "update_a_b_test_variant",
      "title": "Update A/B Test Variant",
      "category": "Sequences",
      "description": "Edits variant B content and config of the A/B test on a step.",
      "method": "PATCH",
      "path": "/sequences/{sequenceId}/steps/{stepId}/ab-test",
      "path_params": [
        "sequenceId",
        "stepId"
      ],
      "query_params": [],
      "body_content_type": "application/json",
      "body_required": false,
      "body_properties": [
        {
          "name": "subject",
          "type": "string",
          "required": false,
          "description": "Variant B subject. An empty string removes it: variant B then replies in the thread of the previous email sent to the lead in this campaign, like variant A would."
        },
        {
          "name": "message",
          "type": "string",
          "required": false,
          "description": "Variant B body (HTML). An empty string is rejected, except on LinkedIn invite steps where it means \"invite without a note\""
        },
        {
          "name": "altMessage",
          "type": "string",
          "required": false,
          "description": "Variant B's LinkedIn note, same meaning as the step-level `altMessage`: the premium invitation note on a `linkedinInvite` step, the out-of-network note on a `linkedinSend` one. On a `linkedinInvite` step, over 300 characters is rejected with `400`"
        },
        {
          "name": "altMessagePremium",
          "type": "string",
          "required": false,
          "description": "Variant B's premium variant of the out-of-network note, on `linkedinSend` steps only: any other step type is rejected with `400`. Over 300 characters is rejected with `400` too"
        },
        {
          "name": "cc",
          "type": "array",
          "required": false,
          "description": ""
        },
        {
          "name": "plainText",
          "type": "boolean",
          "required": false,
          "description": ""
        }
      ],
      "source": "https://developer.lemlist.com/api-reference/endpoints/sequences/update-ab-test-variant.md"
    },
    {
      "name": "delete_a_b_test_variant",
      "title": "Delete A/B Test Variant",
      "category": "Sequences",
      "description": "Deletes a variant of the A/B test and ends the test.",
      "method": "DELETE",
      "path": "/sequences/{sequenceId}/steps/{stepId}/ab-test",
      "path_params": [
        "sequenceId",
        "stepId"
      ],
      "query_params": [
        {
          "name": "variant",
          "type": "string",
          "required": false,
          "description": "Which variant to delete. Defaults to `B`."
        }
      ],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/sequences/delete-ab-test-variant.md"
    },
    {
      "name": "select_a_b_test_winner",
      "title": "Select A/B Test Winner",
      "category": "Sequences",
      "description": "Selects the winning A/B test variant, applied to all remaining leads.",
      "method": "POST",
      "path": "/sequences/{sequenceId}/steps/{stepId}/ab-test/winner",
      "path_params": [
        "sequenceId",
        "stepId"
      ],
      "query_params": [],
      "body_content_type": "application/json",
      "body_required": true,
      "body_properties": [
        {
          "name": "variant",
          "type": "string",
          "required": true,
          "description": "The winning variant"
        }
      ],
      "source": "https://developer.lemlist.com/api-reference/endpoints/sequences/select-ab-test-winner.md"
    },
    {
      "name": "list_message_templates",
      "title": "List Message Templates",
      "category": "Message templates",
      "description": "Lists the team's library message templates, newest first.",
      "method": "GET",
      "path": "/message-templates",
      "path_params": [],
      "query_params": [
        {
          "name": "search",
          "type": "string",
          "required": false,
          "description": "Substring of the name, case-insensitive. Accented a, c, e, i, n, o, u, y match their plain letters (`relance` finds `Rélance`). Names only: bodies and subjects are not searched. Maximum 100 characters; a blank value is no filter."
        },
        {
          "name": "tags",
          "type": "string",
          "required": false,
          "description": "Keep the templates carrying any of these tags. Comma-separated; the parameter may also be repeated (`?tags=a&tags=b`), which keeps a comma inside a tag reachable. Tags are matched trimmed and lowercased, as the library stores them. Maximum 20."
        },
        {
          "name": "userIds",
          "type": "string",
          "required": false,
          "description": "Keep the items created by any of these users (`usr_` ids, see GET /team/members). Comma-separated; the parameter may also be repeated. Maximum 100. Omit for every creator."
        },
        {
          "name": "page",
          "type": "integer",
          "required": false,
          "description": "Page number to retrieve, starting at 1"
        },
        {
          "name": "limit",
          "type": "integer",
          "required": false,
          "description": "Number of items per page. Maximum value: 100"
        }
      ],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/message-templates/list-message-templates.md"
    },
    {
      "name": "list_message_template_tags",
      "title": "List Message Template Tags",
      "category": "Message templates",
      "description": "Lists the distinct tags of the team's library message templates, alphabetically.",
      "method": "GET",
      "path": "/message-templates/tags",
      "path_params": [],
      "query_params": [
        {
          "name": "search",
          "type": "string",
          "required": false,
          "description": "Substring of the name, case-insensitive. Accented a, c, e, i, n, o, u, y match their plain letters (`relance` finds `Rélance`). Names only: bodies and subjects are not searched. Maximum 100 characters; a blank value is no filter."
        },
        {
          "name": "userIds",
          "type": "string",
          "required": false,
          "description": "Keep the items created by any of these users (`usr_` ids, see GET /team/members). Comma-separated; the parameter may also be repeated. Maximum 100. Omit for every creator."
        },
        {
          "name": "page",
          "type": "integer",
          "required": false,
          "description": "Page number to retrieve, starting at 1"
        },
        {
          "name": "limit",
          "type": "integer",
          "required": false,
          "description": "Number of items per page. Maximum value: 100"
        }
      ],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/message-templates/list-message-template-tags.md"
    },
    {
      "name": "get_message_template",
      "title": "Get Message Template",
      "category": "Message templates",
      "description": "Returns one library message template with its body.",
      "method": "GET",
      "path": "/message-templates/{templateId}",
      "path_params": [
        "templateId"
      ],
      "query_params": [],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/message-templates/get-message-template.md"
    },
    {
      "name": "list_snippets",
      "title": "List Snippets",
      "category": "Snippets",
      "description": "Lists the team's snippets by name.",
      "method": "GET",
      "path": "/snippets",
      "path_params": [],
      "query_params": [
        {
          "name": "search",
          "type": "string",
          "required": false,
          "description": "Substring of the name, case-insensitive. Accented a, c, e, i, n, o, u, y match their plain letters (`relance` finds `Rélance`). Names only: bodies and subjects are not searched. Maximum 100 characters; a blank value is no filter."
        },
        {
          "name": "userIds",
          "type": "string",
          "required": false,
          "description": "Keep the items created by any of these users (`usr_` ids, see GET /team/members). Comma-separated; the parameter may also be repeated. Maximum 100. Omit for every creator."
        },
        {
          "name": "page",
          "type": "integer",
          "required": false,
          "description": "Page number to retrieve, starting at 1"
        },
        {
          "name": "limit",
          "type": "integer",
          "required": false,
          "description": "Number of items per page. Maximum value: 100"
        }
      ],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/snippets/list-snippets.md"
    },
    {
      "name": "get_snippet",
      "title": "Get Snippet",
      "category": "Snippets",
      "description": "Returns one snippet with its content.",
      "method": "GET",
      "path": "/snippets/{snippetId}",
      "path_params": [
        "snippetId"
      ],
      "query_params": [],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/snippets/get-snippet.md"
    },
    {
      "name": "create_schedule",
      "title": "Create Schedule",
      "category": "Schedules",
      "description": "Creates a new schedule with customizable timing and timezone settings.",
      "method": "POST",
      "path": "/schedules",
      "path_params": [],
      "query_params": [],
      "body_content_type": "application/json",
      "body_required": true,
      "body_properties": [
        {
          "name": "name",
          "type": "string",
          "required": true,
          "description": "The name of the schedule"
        },
        {
          "name": "secondsToWait",
          "type": "integer",
          "required": false,
          "description": "Delay in seconds between operations"
        },
        {
          "name": "timezone",
          "type": "string",
          "required": true,
          "description": "Timezone for the schedule (e.g., 'Europe/Paris')"
        },
        {
          "name": "start",
          "type": "string",
          "required": true,
          "description": "Start time in HH:mm format"
        },
        {
          "name": "end",
          "type": "string",
          "required": true,
          "description": "End time in HH:mm format"
        },
        {
          "name": "weekdays",
          "type": "array",
          "required": true,
          "description": "Days of the week the schedule is active (1=Monday, 7=Sunday)"
        },
        {
          "name": "public",
          "type": "boolean",
          "required": false,
          "description": "Set to true to make the schedule visible to use as a template"
        }
      ],
      "source": "https://developer.lemlist.com/api-reference/endpoints/schedules/create-schedule.md"
    },
    {
      "name": "get_schedule",
      "title": "Get Schedule",
      "category": "Schedules",
      "description": "Retrieves details of a specific schedule.",
      "method": "GET",
      "path": "/schedules/{scheduleId}",
      "path_params": [
        "scheduleId"
      ],
      "query_params": [],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/schedules/get-schedule.md"
    },
    {
      "name": "get_many_schedules",
      "title": "Get Many Schedules",
      "category": "Schedules",
      "description": "Retrieves all schedules for your team.",
      "method": "GET",
      "path": "/schedules",
      "path_params": [],
      "query_params": [
        {
          "name": "page",
          "type": "integer",
          "required": false,
          "description": "The page number to retrieve"
        },
        {
          "name": "offset",
          "type": "integer",
          "required": false,
          "description": "The number of records to skip. Used if page is not provided."
        },
        {
          "name": "limit",
          "type": "integer",
          "required": false,
          "description": "The maximum number of records to return"
        },
        {
          "name": "sortBy",
          "type": "string",
          "required": false,
          "description": "The field by which to sort the schedules. Currently, only 'createdAt' is supported."
        },
        {
          "name": "sortOrder",
          "type": "string",
          "required": false,
          "description": "The sort direction. Use 'desc' for descending order; any other value (or omission) will sort in ascending order."
        }
      ],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/schedules/get-many-schedules.md"
    },
    {
      "name": "update_schedule",
      "title": "Update Schedule",
      "category": "Schedules",
      "description": "Updates an existing schedule's parameters.",
      "method": "PATCH",
      "path": "/schedules/{scheduleId}",
      "path_params": [
        "scheduleId"
      ],
      "query_params": [],
      "body_content_type": "application/json",
      "body_required": true,
      "body_properties": [
        {
          "name": "name",
          "type": "string",
          "required": false,
          "description": "The name of the schedule"
        },
        {
          "name": "secondsToWait",
          "type": "integer",
          "required": false,
          "description": "Delay in seconds between operations"
        },
        {
          "name": "timezone",
          "type": "string",
          "required": false,
          "description": "Timezone for the schedule (e.g., 'Europe/Paris')"
        },
        {
          "name": "start",
          "type": "string",
          "required": false,
          "description": "Start time in HH:mm format"
        },
        {
          "name": "end",
          "type": "string",
          "required": false,
          "description": "End time in HH:mm format"
        },
        {
          "name": "weekdays",
          "type": "array",
          "required": false,
          "description": "Days of the week the schedule is active (1=Monday, 7=Sunday)"
        },
        {
          "name": "public",
          "type": "boolean",
          "required": false,
          "description": "Set to true to make the schedule visible to use as a template"
        }
      ],
      "source": "https://developer.lemlist.com/api-reference/endpoints/schedules/update-schedule.md"
    },
    {
      "name": "delete_schedule",
      "title": "Delete Schedule",
      "category": "Schedules",
      "description": "Deletes a specific schedule.",
      "method": "DELETE",
      "path": "/schedules/{scheduleId}",
      "path_params": [
        "scheduleId"
      ],
      "query_params": [],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/schedules/delete-schedule.md"
    },
    {
      "name": "get_campaign_schedules",
      "title": "Get Campaign Schedules",
      "category": "Schedules",
      "description": "Retrieves all schedules associated with a specific campaign.",
      "method": "GET",
      "path": "/campaigns/{campaignId}/schedules/",
      "path_params": [
        "campaignId"
      ],
      "query_params": [],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/schedules/get-campaign-schedules.md"
    },
    {
      "name": "associate_schedule_with_campaign",
      "title": "Associate Schedule with Campaign",
      "category": "Schedules",
      "description": "Associates a schedule with a campaign.",
      "method": "POST",
      "path": "/campaigns/{campaignId}/schedules/{scheduleId}",
      "path_params": [
        "campaignId",
        "scheduleId"
      ],
      "query_params": [],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/schedules/associate-schedule-with-campaign.md"
    },
    {
      "name": "get_campaign_leads",
      "title": "Get Campaign Leads",
      "category": "Leads",
      "description": "Retrieves leads from a specific campaign, optionally filtered by state.",
      "method": "GET",
      "path": "/campaigns/{campaignId}/leads/",
      "path_params": [
        "campaignId"
      ],
      "query_params": [
        {
          "name": "state",
          "type": "string",
          "required": false,
          "description": "Filter leads by state (e.g., scanned, contacted, interested, notInterested, etc.)"
        },
        {
          "name": "limit",
          "type": "integer",
          "required": false,
          "description": "Maximum number of leads to return. Default: 100, Max: 500"
        }
      ],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/leads/get-campaign-leads.md"
    },
    {
      "name": "get_lead_by_email_or_id",
      "title": "Get Lead by Email or ID",
      "category": "Leads",
      "description": "Retrieves a lead using their email address or lead ID.",
      "method": "GET",
      "path": "/leads",
      "path_params": [],
      "query_params": [
        {
          "name": "id",
          "type": "string",
          "required": false,
          "description": "The lead ID. You should use at least one of 'email' or 'id'."
        },
        {
          "name": "email",
          "type": "string",
          "required": false,
          "description": "The lead email. You should use at least one of 'email' or 'id'."
        },
        {
          "name": "version",
          "type": "string",
          "required": false,
          "description": "API version. v2 is the only option"
        }
      ],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/leads/get-lead-by-email-or-id.md"
    },
    {
      "name": "update_lead_in_a_campaign",
      "title": "Update Lead in a Campaign",
      "category": "Leads",
      "description": "Updates an existing lead's information in a specific campaign.",
      "method": "PATCH",
      "path": "/campaigns/{campaignId}/leads/{leadId}",
      "path_params": [
        "campaignId",
        "leadId"
      ],
      "query_params": [
        {
          "name": "updateStrategy",
          "type": "string",
          "required": false,
          "description": "What the lead, its contact and its company keep. `overwrite` (default): sent values replace stored ones, an empty string clears. `overwriteIgnoreEmpty`: empty values ignored. `fillEmptyOnly`: only empty fields filled, identifiers, links, owner and status kept. Other values: 400."
        }
      ],
      "body_content_type": "application/json",
      "body_required": false,
      "body_properties": [
        {
          "name": "firstName",
          "type": "string",
          "required": false,
          "description": ""
        },
        {
          "name": "lastName",
          "type": "string",
          "required": false,
          "description": ""
        },
        {
          "name": "companyName",
          "type": "string",
          "required": false,
          "description": "New name of the company the lead is linked to, renamed in place. When the lead has no company yet, it gets linked to a company with that name, created when needed."
        },
        {
          "name": "jobTitle",
          "type": "string",
          "required": false,
          "description": ""
        },
        {
          "name": "preferredContactMethod",
          "type": "string",
          "required": false,
          "description": "Preferred contact method (email, linkedIn)"
        }
      ],
      "source": "https://developer.lemlist.com/api-reference/endpoints/leads/update-lead.md"
    },
    {
      "name": "delete_or_unsubscribe_lead",
      "title": "Delete or Unsubscribe Lead",
      "category": "Leads",
      "description": "Removes a lead from a campaign or unsubscribes it permanently.",
      "method": "DELETE",
      "path": "/campaigns/{campaignId}/leads/{leadId}",
      "path_params": [
        "campaignId",
        "leadId"
      ],
      "query_params": [
        {
          "name": "action",
          "type": "string",
          "required": false,
          "description": "Use 'remove' to force delete. Otherwise it will just unsubscribe the lead from the campaign."
        }
      ],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/leads/delete-lead.md"
    },
    {
      "name": "add_custom_variables_on_leads",
      "title": "Add Custom Variables on Leads",
      "category": "Leads",
      "description": "Adds new custom variables to a lead.",
      "method": "POST",
      "path": "/leads/{leadId}/variables",
      "path_params": [
        "leadId"
      ],
      "query_params": [
        {
          "name": "customField1",
          "type": "string",
          "required": false,
          "description": "Example custom variable"
        },
        {
          "name": "customField2",
          "type": "string",
          "required": false,
          "description": "Example custom variable"
        },
        {
          "name": "customField3",
          "type": "string",
          "required": false,
          "description": "Example custom variable"
        }
      ],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/leads/add-lead-variables.md"
    },
    {
      "name": "update_values_of_custom_variables_of_a_lead",
      "title": "Update Values of Custom Variables of a Lead",
      "category": "Leads",
      "description": "Updates the values of custom variables on a lead.",
      "method": "PATCH",
      "path": "/leads/{leadId}/variables",
      "path_params": [
        "leadId"
      ],
      "query_params": [
        {
          "name": "customField1",
          "type": "string",
          "required": false,
          "description": "Example custom variable"
        },
        {
          "name": "customField2",
          "type": "string",
          "required": false,
          "description": "Example custom variable"
        },
        {
          "name": "customField3",
          "type": "string",
          "required": false,
          "description": "Example custom variable"
        }
      ],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/leads/update-lead-variables.md"
    },
    {
      "name": "erase_values_of_custom_variables_on_a_lead",
      "title": "Erase Values of Custom Variables on a Lead",
      "category": "Leads",
      "description": "Erases the values of custom variables on a lead.",
      "method": "DELETE",
      "path": "/leads/{leadId}/variables",
      "path_params": [
        "leadId"
      ],
      "query_params": [
        {
          "name": "customField1",
          "type": "string",
          "required": false,
          "description": "Example custom variable"
        },
        {
          "name": "customField2",
          "type": "string",
          "required": false,
          "description": "Example custom variable"
        },
        {
          "name": "customField3",
          "type": "string",
          "required": false,
          "description": "Example custom variable"
        }
      ],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/leads/delete-lead-variables.md"
    },
    {
      "name": "unsubscribe_lead_from_campaign",
      "title": "Unsubscribe Lead from Campaign",
      "category": "Leads",
      "description": "Unsubscribes a lead from a lemlist campaign.",
      "method": "DELETE",
      "path": "/campaigns/{campaignId}/leads/{email}",
      "path_params": [
        "campaignId",
        "email"
      ],
      "query_params": [],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/leads/unsubscribe-lead-from-campaign.md"
    },
    {
      "name": "pause_lead",
      "title": "Pause Lead",
      "category": "Leads",
      "description": "Pauses a lead's activity in all campaigns or a specific campaign.",
      "method": "POST",
      "path": "/leads/pause/{leadId}",
      "path_params": [
        "leadId"
      ],
      "query_params": [
        {
          "name": "campaignId",
          "type": "string",
          "required": false,
          "description": "ID of the campaign. If provided, pauses the lead only in that campaign."
        }
      ],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/leads/pause-lead.md"
    },
    {
      "name": "resume_paused_lead",
      "title": "Resume Paused Lead",
      "category": "Leads",
      "description": "Resumes a paused lead in all campaigns or a specific campaign.",
      "method": "POST",
      "path": "/leads/start/{leadId}",
      "path_params": [
        "leadId"
      ],
      "query_params": [],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/leads/resume-paused-lead.md"
    },
    {
      "name": "launch_lead",
      "title": "Launch Lead",
      "category": "Leads",
      "description": "Manually launches (reviews) a single lead in its campaign.",
      "method": "POST",
      "path": "/leads/review/{leadId}",
      "path_params": [
        "leadId"
      ],
      "query_params": [],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/leads/launch-lead.md"
    },
    {
      "name": "mark_lead_as_interested",
      "title": "Mark Lead as Interested",
      "category": "Leads",
      "description": "Marks a lead as interested across all campaigns.",
      "method": "POST",
      "path": "/leads/interested/{leadIdOrEmail}",
      "path_params": [
        "leadIdOrEmail"
      ],
      "query_params": [],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/leads/mark-lead-as-interested.md"
    },
    {
      "name": "mark_lead_as_not_interested",
      "title": "Mark Lead as Not Interested",
      "category": "Leads",
      "description": "Marks a lead as not interested across all campaigns.",
      "method": "POST",
      "path": "/leads/notinterested/{leadIdOrEmail}",
      "path_params": [
        "leadIdOrEmail"
      ],
      "query_params": [],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/leads/mark-lead-as-not-interested.md"
    },
    {
      "name": "mark_lead_as_interested_in_campaign",
      "title": "Mark Lead as Interested in Campaign",
      "category": "Leads",
      "description": "Marks a lead as interested in a specific campaign.",
      "method": "POST",
      "path": "/campaigns/{campaignId}/leads/{leadIdOrEmail}/interested",
      "path_params": [
        "campaignId",
        "leadIdOrEmail"
      ],
      "query_params": [],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/leads/mark-lead-as-interested-in-campaign.md"
    },
    {
      "name": "mark_lead_as_not_interested_in_campaign",
      "title": "Mark Lead as Not Interested in Campaign",
      "category": "Leads",
      "description": "Marks a lead as not interested in a specific campaign.",
      "method": "POST",
      "path": "/campaigns/{campaignId}/leads/{leadIdOrEmail}/notinterested",
      "path_params": [
        "campaignId",
        "leadIdOrEmail"
      ],
      "query_params": [],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/leads/mark-lead-as-not-interested-in-campaign.md"
    },
    {
      "name": "skip_step_for_lead",
      "title": "Skip Step for Lead",
      "category": "Leads",
      "description": "Skips one step of a running campaign for a single lead.",
      "method": "POST",
      "path": "/campaigns/{campaignId}/leads/{leadIdOrEmail}/steps/{stepId}/skip",
      "path_params": [
        "campaignId",
        "leadIdOrEmail",
        "stepId"
      ],
      "query_params": [],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/leads/skip-step-for-lead.md"
    },
    {
      "name": "personalize_step_for_lead",
      "title": "Personalize Step for Lead",
      "category": "Leads",
      "description": "Personalizes the message of one campaign step for a single lead.",
      "method": "PUT",
      "path": "/campaigns/{campaignId}/leads/{leadIdOrEmail}/steps/{stepId}/personalization",
      "path_params": [
        "campaignId",
        "leadIdOrEmail",
        "stepId"
      ],
      "query_params": [],
      "body_content_type": "application/json",
      "body_required": false,
      "body_properties": [
        {
          "name": "variant",
          "type": "string",
          "required": false,
          "description": "A/B variant to write on. Defaults to the variant the lead is already on: the winner once one is picked, else the variant already personalized, else the variant of the lead's scheduled task, else A."
        },
        {
          "name": "subject",
          "type": "string",
          "required": false,
          "description": "Email steps only. On a follow-up email, a non-empty subject starts a new thread; omit it to stay in the thread."
        },
        {
          "name": "message",
          "type": "string",
          "required": false,
          "description": "The message body. HTML on email steps; plain text on LinkedIn, SMS and WhatsApp steps (HTML is converted to text). Cannot be blank, except on a LinkedIn invitation."
        },
        {
          "name": "cc",
          "type": "array",
          "required": false,
          "description": "Email steps only. An empty array removes the cc for this lead."
        },
        {
          "name": "plainText",
          "type": "boolean",
          "required": false,
          "description": "Email steps only. Send this lead a plain-text email."
        },
        {
          "name": "altMessage",
          "type": "string",
          "required": false,
          "description": "LinkedIn invitation and LinkedIn message steps only. The connection-request note, 300 characters at most on an invitation."
        },
        {
          "name": "altMessagePremium",
          "type": "string",
          "required": false,
          "description": "LinkedIn message steps only. The note sent from a premium account."
        }
      ],
      "source": "https://developer.lemlist.com/api-reference/endpoints/leads/personalize-step-for-lead.md"
    },
    {
      "name": "reset_step_personalization_for_lead",
      "title": "Reset Step Personalization for Lead",
      "category": "Leads",
      "description": "Removes a lead's personalization of one campaign step.",
      "method": "DELETE",
      "path": "/campaigns/{campaignId}/leads/{leadIdOrEmail}/steps/{stepId}/personalization",
      "path_params": [
        "campaignId",
        "leadIdOrEmail",
        "stepId"
      ],
      "query_params": [],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/leads/reset-step-personalization-for-lead.md"
    },
    {
      "name": "import_leads_from_crm",
      "title": "Import Leads from CRM",
      "category": "Leads",
      "description": "Links a campaign to a filter of your connected CRM and imports its records as leads, now and as the filter picks up new ones.",
      "method": "POST",
      "path": "/campaigns/{campaignId}/leads/import",
      "path_params": [
        "campaignId"
      ],
      "query_params": [],
      "body_content_type": "application/json",
      "body_required": false,
      "body_properties": [
        {
          "name": "filterId",
          "type": "string",
          "required": true,
          "description": "Filter ID returned by [Get CRM Filters](/api-reference/endpoints/crm/get-crm-filters)"
        },
        {
          "name": "filterType",
          "type": "string",
          "required": false,
          "description": "Salesforce only: `lead` or `contact` list views, or `report`. Ignored by HubSpot and Pipedrive. Defaults to `lead` when your Salesforce connection allows Leads, `contact` otherwise."
        },
        {
          "name": "userId",
          "type": "string",
          "required": false,
          "description": "Salesforce only, for a list view scoped to its owner (\"My leads\", \"My contacts\"…): the team member the view is read as. They must have their own Salesforce account connected in lemlist. Leave it out in every other case (reports, views not scoped to an owner); it is ignored for HubSpot and Pipedrive, where your team's CRM connection is used."
        },
        {
          "name": "deduplicate",
          "type": "string",
          "required": false,
          "description": "`all` (or `true`) skips contacts already in another campaign, `activeOnly` skips only contacts still active in another campaign, `off` (or `false`, the default) imports everyone."
        },
        {
          "name": "enrichFeature",
          "type": "string",
          "required": false,
          "description": "Enrichments to run on every imported lead, as an array or a `|`-separated string (e.g. `find_email|verify`). Consumes credits for each lead."
        }
      ],
      "source": "https://developer.lemlist.com/api-reference/endpoints/leads/import-leads-from-crm.md"
    },
    {
      "name": "upload_audio_for_voice_message_step",
      "title": "Upload Audio for Voice Message Step",
      "category": "Leads",
      "description": "Uploads an audio file for voice message steps in campaign sequences.",
      "method": "POST",
      "path": "/leads/audio",
      "path_params": [],
      "query_params": [
        {
          "name": "leadId",
          "type": "string",
          "required": true,
          "description": "The unique identifier of the lead"
        },
        {
          "name": "stepId",
          "type": "string",
          "required": true,
          "description": "The unique identifier of the voice message step"
        }
      ],
      "body_content_type": "multipart/form-data",
      "body_required": false,
      "body_properties": [
        {
          "name": "file",
          "type": "string",
          "required": false,
          "description": "Audio file to upload"
        }
      ],
      "source": "https://developer.lemlist.com/api-reference/endpoints/leads/upload-audio-for-voice-message-step.md"
    },
    {
      "name": "add_and_update_company",
      "title": "Add and update company",
      "category": "Companies",
      "description": "Creates a new company or updates an existing one based on domain or LinkedIn URL.",
      "method": "POST",
      "path": "/companies",
      "path_params": [],
      "query_params": [
        {
          "name": "updateStrategy",
          "type": "string",
          "required": false,
          "description": "What an existing record keeps. `overwriteIgnoreEmpty` (default): sent values replace stored ones, empty values are ignored. `overwrite`: an empty string clears the field. `fillEmptyOnly`: only empty fields are filled, identifiers, links, owner and status kept. A new record receives every value sent. Other values: `400 INVALID_UPDATE_STRATEGY`."
        }
      ],
      "body_content_type": "application/json",
      "body_required": true,
      "body_properties": [
        {
          "name": "companyId",
          "type": "string",
          "required": false,
          "description": "Existing company ID. Updates a specific company by ID, bypassing domain/LinkedIn matching. Can only be used to update an existing company, not to create a new one. When provided, `name` and the identifiers become optional."
        },
        {
          "name": "name",
          "type": "string",
          "required": false,
          "description": "Company name. Required unless `companyId` is provided."
        },
        {
          "name": "domain",
          "type": "string",
          "required": false,
          "description": "Company website domain (e.g. `lemlist.com`). Used as a unique key for upsert matching. Without `companyId`, at least one identifier is required among `domain`, `linkedinUrl` and `linkedinUrlSalesNav`."
        },
        {
          "name": "linkedinUrl",
          "type": "string",
          "required": false,
          "description": "LinkedIn company page URL. Used as an alternative unique key for upsert matching, and accepted as the sole identifier of a new company."
        },
        {
          "name": "linkedinUrlSalesNav",
          "type": "string",
          "required": false,
          "description": "LinkedIn Sales Navigator company URL. Used as an alternative unique key for upsert matching, and accepted as the sole identifier of a new company."
        },
        {
          "name": "companyOwner",
          "type": "string",
          "required": false,
          "description": "Owner of the company. Can be a user ID (e.g. `usr_...`) or a team member's email address. If the provided value does not match a team member, the company is still written with an `OWNER_NOT_FOUND` or `INVALID_OWNER_FORMAT` entry in `warnings`: the owner defaults to the API key owner on creation and is unchanged on update. On update it replaces the current owner, except under `fillEmptyOnly` where it is only set when the company has none."
        },
        {
          "name": "industry",
          "type": "string",
          "required": false,
          "description": "Industry sector of the company."
        },
        {
          "name": "location",
          "type": "string",
          "required": false,
          "description": "Geographic location of the company."
        },
        {
          "name": "size",
          "type": "string",
          "required": false,
          "description": "Company size."
        },
        {
          "name": "specialties",
          "type": "string",
          "required": false,
          "description": "Company specialties."
        },
        {
          "name": "tagline",
          "type": "string",
          "required": false,
          "description": "Company tagline."
        },
        {
          "name": "type",
          "type": "string",
          "required": false,
          "description": "Company type."
        },
        {
          "name": "description",
          "type": "string",
          "required": false,
          "description": "Company description."
        },
        {
          "name": "foundedOn",
          "type": "string",
          "required": false,
          "description": "Company founding date."
        },
        {
          "name": "headquarters",
          "type": "string",
          "required": false,
          "description": "Company headquarters location."
        },
        {
          "name": "picture",
          "type": "string",
          "required": false,
          "description": "URL of the company logo or picture."
        },
        {
          "name": "source",
          "type": "string",
          "required": false,
          "description": "Origin of the company record. Set on creation only and cannot be updated afterwards. Defaults to `api`."
        }
      ],
      "source": "https://developer.lemlist.com/api-reference/endpoints/companies/upsert-company.md"
    },
    {
      "name": "get_many_companies",
      "title": "Get Many Companies",
      "category": "Companies",
      "description": "Retrieves companies from your CRM. Use `idsOrDomains` to fetch specific companies by ID or domain in a single request (max 100), or omit it to get a paginated list of all companies.",
      "method": "GET",
      "path": "/companies",
      "path_params": [],
      "query_params": [
        {
          "name": "idsOrDomains",
          "type": "string",
          "required": false,
          "description": "Comma-separated list of company IDs or domains to fetch. When provided, returns only matching companies (no pagination). Each value is classified as a company ID (e.g. `cpn_xxx`) or a domain (e.g. `example.com`). URLs are normalized automatically (e.g. `https://example.com/path` → `example.com`). Invalid values are silently skipped. Maximum 100 values."
        },
        {
          "name": "offset",
          "type": "integer",
          "required": false,
          "description": "Number of companies to skip for pagination. Defaults to 0. Ignored when `idsOrDomains` is provided."
        },
        {
          "name": "sortBy",
          "type": "string",
          "required": false,
          "description": "The field by which to sort. Currently, only 'createdAt' is supported."
        },
        {
          "name": "sortOrder",
          "type": "string",
          "required": false,
          "description": "The sort direction. Use 'desc' for descending order; any other value (or omission) will sort in ascending order."
        },
        {
          "name": "search",
          "type": "string",
          "required": false,
          "description": "Search by company name (case insensitive)"
        },
        {
          "name": "fields",
          "type": "string",
          "required": false,
          "description": "Returns selected fields. Returns all fields if empty. Each field is separated by a comma (e.g., '_id,fields.name,domain')"
        },
        {
          "name": "limit",
          "type": "integer",
          "required": false,
          "description": "Number of companies to retrieve. Default: 100. Maximum: 500"
        },
        {
          "name": "listId",
          "type": "string",
          "required": false,
          "description": "Filter companies to the members of a static CRM company list (`clt_xxx` format). Combines with every other filter. Ignored when `idsOrDomains` is provided."
        },
        {
          "name": "crmSyncStatus",
          "type": "string",
          "required": false,
          "description": "Filter companies by their CRM sync state against the team's active CRM provider. Requires a CRM (Hubspot, Salesforce, or Pipedrive) to be connected — otherwise the request returns `400 NO_CRM_CONNECTED`. Common values:\n- `synced` — the company has a CRM record and no sync errors.\n- `not_synced` — the company has no CRM record yet.\n- `error` — at least one sync error is currently raised.\n- A specific error reason (lowercase form), to filter by root cause: `unique_index_error_company`, `property_d"
        },
        {
          "name": "fieldRejectionReason",
          "type": "string",
          "required": false,
          "description": "Filter companies to those carrying a field rejection with this reason — a value lemlist refused to write, raised during CRM sync (`crm_sync_*`). Returns an empty list (`total: 0`) when no company matches. Each returned company exposes the full detail under `fieldRejections[]` (which field, why, and `conflictingRecordId` for duplicates). Independent of `crmSyncStatus` (which keys off the live provider errors); this filter reads the stored field rejections. Only applies to the paginated list — ign"
        }
      ],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/companies/get-many-companies.md"
    },
    {
      "name": "delete_company",
      "title": "Delete Company",
      "category": "Companies",
      "description": "Deletes a lemlist company. Use `force=true` to detach attached contacts before deletion.",
      "method": "DELETE",
      "path": "/companies/{companyId}",
      "path_params": [
        "companyId"
      ],
      "query_params": [
        {
          "name": "force",
          "type": "boolean",
          "required": false,
          "description": "When `true`, detaches contacts attached to this company (unsets their `companyId`) before deleting it. When omitted or `false`, the request fails with `400 COMPANY_HAS_CONTACTS` if any contact is still attached."
        }
      ],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/companies/delete-company.md"
    },
    {
      "name": "merge_companies",
      "title": "Merge Companies",
      "category": "Companies",
      "description": "Merges up to 10 lemlist companies into one survivor, moving everything attached to the deleted companies onto it.",
      "method": "POST",
      "path": "/companies/merge",
      "path_params": [],
      "query_params": [],
      "body_content_type": "application/json",
      "body_required": true,
      "body_properties": [
        {
          "name": "primaryId",
          "type": "string",
          "required": true,
          "description": "The surviving company. A lemlist company id (`cpn_xxx`)."
        },
        {
          "name": "secondaryIds",
          "type": "array",
          "required": true,
          "description": "The companies folded into the survivor then deleted, 9 at most. A lemlist company id (`cpn_xxx`). Must not contain `primaryId`, and each company is listed once."
        }
      ],
      "source": "https://developer.lemlist.com/api-reference/endpoints/companies/merge-companies.md"
    },
    {
      "name": "get_company_lists",
      "title": "Get Company Lists",
      "category": "Companies",
      "description": "Retrieves all company lists for the team, with optional name filtering.",
      "method": "GET",
      "path": "/companies/lists",
      "path_params": [],
      "query_params": [
        {
          "name": "search",
          "type": "string",
          "required": false,
          "description": "Filter lists by name (case-insensitive partial match)."
        }
      ],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/companies/get-company-lists.md"
    },
    {
      "name": "create_company_list",
      "title": "Create Company List",
      "category": "Companies",
      "description": "Creates a new static company list.",
      "method": "POST",
      "path": "/companies/lists",
      "path_params": [],
      "query_params": [],
      "body_content_type": "application/json",
      "body_required": true,
      "body_properties": [
        {
          "name": "name",
          "type": "string",
          "required": true,
          "description": "Name of the company list to create (max 200 characters). Cannot contain `<` or `>`."
        }
      ],
      "source": "https://developer.lemlist.com/api-reference/endpoints/companies/create-company-list.md"
    },
    {
      "name": "add_or_remove_companies_in_a_list",
      "title": "Add or Remove Companies in a List",
      "category": "Companies",
      "description": "Add companies to a static company list, or remove them with ?action=remove.",
      "method": "POST",
      "path": "/companies/lists/{listId}/entities",
      "path_params": [
        "listId"
      ],
      "query_params": [
        {
          "name": "action",
          "type": "string",
          "required": false,
          "description": "Omit to **add** the companies to the list. Set to `remove` to **remove** them from the list."
        }
      ],
      "body_content_type": "application/json",
      "body_required": true,
      "body_properties": [
        {
          "name": "companyIds",
          "type": "array",
          "required": true,
          "description": "Array of company IDs (`cpn_xxx` format) to add to or remove from the list. Required, non-empty, maximum 1,000 per request."
        }
      ],
      "source": "https://developer.lemlist.com/api-reference/endpoints/companies/manage-company-list-entities.md"
    },
    {
      "name": "create_company_note",
      "title": "Create Company Note",
      "category": "Companies",
      "description": "Creates a new note attached to a specific company.",
      "method": "POST",
      "path": "/companies/{companyId}/notes",
      "path_params": [
        "companyId"
      ],
      "query_params": [],
      "body_content_type": "application/json",
      "body_required": false,
      "body_properties": [
        {
          "name": "note",
          "type": "string",
          "required": true,
          "description": "The note content"
        }
      ],
      "source": "https://developer.lemlist.com/api-reference/endpoints/companies/create-company-note.md"
    },
    {
      "name": "get_company_notes",
      "title": "Get Company Notes",
      "category": "Companies",
      "description": "Retrieves all notes associated with a specific company.",
      "method": "GET",
      "path": "/companies/{companyId}/notes",
      "path_params": [
        "companyId"
      ],
      "query_params": [
        {
          "name": "limit",
          "type": "integer",
          "required": false,
          "description": "Number of notes to retrieve. Default: 100. Maximum: 100"
        },
        {
          "name": "page",
          "type": "integer",
          "required": false,
          "description": "Page number to retrieve"
        },
        {
          "name": "sortBy",
          "type": "string",
          "required": false,
          "description": "The field by which to sort. Currently, only 'createdAt' is supported."
        },
        {
          "name": "sortOrder",
          "type": "string",
          "required": false,
          "description": "The sort direction. Use 'desc' for descending order; any other value (or omission) will sort in ascending order."
        }
      ],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/companies/get-company-notes.md"
    },
    {
      "name": "add_and_update_contact",
      "title": "Add and update contact",
      "category": "Contacts",
      "description": "Creates a new contact or updates an existing one based on email or LinkedIn URL.",
      "method": "POST",
      "path": "/contacts",
      "path_params": [],
      "query_params": [
        {
          "name": "updateStrategy",
          "type": "string",
          "required": false,
          "description": "What an existing record keeps. `overwriteIgnoreEmpty` (default): sent values replace stored ones, empty values are ignored. `overwrite`: an empty string clears the field. `fillEmptyOnly`: only empty fields are filled, identifiers, links, owner and status kept. A new record receives every value sent. Other values: `400 INVALID_UPDATE_STRATEGY`."
        }
      ],
      "body_content_type": "application/json",
      "body_required": true,
      "body_properties": [
        {
          "name": "contactId",
          "type": "string",
          "required": false,
          "description": "Existing contact ID. Updates a specific contact by ID, bypassing email/LinkedIn matching. Can only be used to update an existing contact, not to create a new one. When provided, `email` and `linkedinUrl` are not required. At least one of `contactId`, `email`, `linkedinUrl`, or `linkedinUrlSalesNav` is required."
        },
        {
          "name": "email",
          "type": "string",
          "required": false,
          "description": "Contact email address. Used as a unique key for upsert matching. At least one of `contactId`, `email`, `linkedinUrl`, or `linkedinUrlSalesNav` is required."
        },
        {
          "name": "linkedinUrl",
          "type": "string",
          "required": false,
          "description": "LinkedIn profile URL. Used as an alternative unique key for upsert matching. At least one of `contactId`, `email`, `linkedinUrl`, or `linkedinUrlSalesNav` is required."
        },
        {
          "name": "linkedinUrlSalesNav",
          "type": "string",
          "required": false,
          "description": "LinkedIn Sales Navigator profile URL. Used as an alternative unique key for upsert matching."
        },
        {
          "name": "additionalEmails",
          "type": "array",
          "required": false,
          "description": "Additional email addresses for the contact. Each must be a valid email address."
        },
        {
          "name": "firstName",
          "type": "string",
          "required": false,
          "description": "Contact first name."
        },
        {
          "name": "lastName",
          "type": "string",
          "required": false,
          "description": "Contact last name."
        },
        {
          "name": "phone",
          "type": "string",
          "required": false,
          "description": "Contact phone number."
        },
        {
          "name": "jobTitle",
          "type": "string",
          "required": false,
          "description": "Contact job title. If a company is linked, this is saved as part of the job data."
        },
        {
          "name": "jobDescription",
          "type": "string",
          "required": false,
          "description": "Contact job description. If a company is linked, this is saved as part of the job data."
        },
        {
          "name": "picture",
          "type": "string",
          "required": false,
          "description": "URL of the contact's profile picture."
        },
        {
          "name": "timezone",
          "type": "string",
          "required": false,
          "description": "Contact timezone."
        },
        {
          "name": "industry",
          "type": "string",
          "required": false,
          "description": "Contact industry."
        },
        {
          "name": "languages",
          "type": "string",
          "required": false,
          "description": "Contact languages."
        },
        {
          "name": "location",
          "type": "string",
          "required": false,
          "description": "Contact location."
        },
        {
          "name": "skills",
          "type": "string",
          "required": false,
          "description": "Contact skills."
        },
        {
          "name": "summary",
          "type": "string",
          "required": false,
          "description": "Contact summary or bio."
        },
        {
          "name": "tagline",
          "type": "string",
          "required": false,
          "description": "Contact tagline."
        },
        {
          "name": "contactOwner",
          "type": "string",
          "required": false,
          "description": "Owner of the contact. Can be a user ID (e.g. `usr_...`) or a team member's email address. If the provided value does not match a team member, the contact is still written with an `OWNER_NOT_FOUND` or `INVALID_OWNER_FORMAT` entry in `warnings`: the owner defaults to the API key owner on creation and is unchanged on update. On update it replaces the current owner, except under `fillEmptyOnly` where it is only set when the contact has none."
        },
        {
          "name": "source",
          "type": "string",
          "required": false,
          "description": "Origin of the contact record. Set on creation only and cannot be updated afterwards. Defaults to `api`."
        },
        {
          "name": "companyId",
          "type": "string",
          "required": false,
          "description": "ID of a company already existing in lemlist to link to this contact. Takes priority over `companyDomain` and `companyLinkedinUrl`."
        },
        {
          "name": "companyDomain",
          "type": "string",
          "required": false,
          "description": "Domain of a company already existing in lemlist to link to this contact (e.g. `lemlist.com`). Used if `companyId` is not provided."
        },
        {
          "name": "companyLinkedinUrl",
          "type": "string",
          "required": false,
          "description": "LinkedIn URL of a company already existing in lemlist to link to this contact. Used if `companyId` and `companyDomain` are not provided."
        }
      ],
      "source": "https://developer.lemlist.com/api-reference/endpoints/contacts/upsert-contact.md"
    },
    {
      "name": "get_contact",
      "title": "Get Contact",
      "category": "Contacts",
      "description": "Retrieves a specific contact by their ID or email address.",
      "method": "GET",
      "path": "/contacts/{idOrEmail}",
      "path_params": [
        "idOrEmail"
      ],
      "query_params": [],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/contacts/get-contact.md"
    },
    {
      "name": "get_many_contacts",
      "title": "Get Many Contacts",
      "category": "Contacts",
      "description": "Retrieves contacts from your CRM. Use `idsOrEmails` to fetch specific contacts by ID or email in a single request (max 100), or omit it to search/list contacts by name, email, contact list, or campaign membership.",
      "method": "GET",
      "path": "/contacts",
      "path_params": [],
      "query_params": [
        {
          "name": "idsOrEmails",
          "type": "string",
          "required": false,
          "description": "A comma separated string of either valid contact IDs (MongoDB ObjectId) or valid email addresses. Optional — when omitted, returns the paginated list of all contacts of the team. Maximum 100 values."
        },
        {
          "name": "search",
          "type": "string",
          "required": false,
          "description": "Search contacts by name or other text fields. Must be at least 2 characters."
        },
        {
          "name": "email",
          "type": "string",
          "required": false,
          "description": "Search contacts by exact email address."
        },
        {
          "name": "listId",
          "type": "string",
          "required": false,
          "description": "Filter contacts by contact list ID (`clt_xxx` format). Can be combined with `search` or `email`, or used alone to list all contacts in a list. Get valid IDs from `GET /contacts/lists`."
        },
        {
          "name": "notInAnyCampaign",
          "type": "boolean",
          "required": false,
          "description": "When set to `true`, only returns contacts that are not part of any campaign (orphan contacts). Can be used alone or combined with other filters such as `search`, `email`, or `listId`."
        },
        {
          "name": "companyId",
          "type": "string",
          "required": false,
          "description": "Filter contacts by attached company ID (`cpn_xxx` format). Use this when you already know the lemlist company id (for example after fetching `GET /companies?crmSyncStatus=unique_index_error_company`). Mutually exclusive with `companyDomain`, `companyLinkedinUrl`, and `companySalesnavUrl`."
        },
        {
          "name": "companyDomain",
          "type": "string",
          "required": false,
          "description": "Filter contacts by their company's website domain. Resolved to a `companyId` against the Companies collection. If no company matches, the endpoint returns an empty list (`total: 0`). Mutually exclusive with the other `company*` filters."
        },
        {
          "name": "companyLinkedinUrl",
          "type": "string",
          "required": false,
          "description": "Filter contacts by their company's LinkedIn URL. Resolved to a `companyId` against the Companies collection. If no company matches, the endpoint returns an empty list (`total: 0`). Mutually exclusive with the other `company*` filters."
        },
        {
          "name": "companySalesnavUrl",
          "type": "string",
          "required": false,
          "description": "Filter contacts by their company's LinkedIn Sales Navigator URL. Resolved to a `companyId` against the Companies collection. If no company matches, the endpoint returns an empty list (`total: 0`). Mutually exclusive with the other `company*` filters."
        },
        {
          "name": "withPrimaryCompany",
          "type": "boolean",
          "required": false,
          "description": "When set to `true`, only returns contacts linked to a company; when set to `false`, only returns contacts without a company. Omit for no filter. Mutually exclusive with the `company*` filters (`companyId`, `companyDomain`, `companyLinkedinUrl`, `companySalesnavUrl`)."
        },
        {
          "name": "fieldRejectionReason",
          "type": "string",
          "required": false,
          "description": "Filter contacts to those carrying a field rejection with this reason — a value lemlist refused to write, prefixed by its origin (`enrichment_*` while enriching, `crm_sync_*` during CRM sync). Returns an empty list (`total: 0`) when no contact matches. Each returned contact exposes the full detail under `fieldRejections[]` (which field, why, and `conflictingRecordId` for duplicates). Only applies to the paginated list — ignored when `idsOrEmails` is provided (that path returns the exact contacts "
        },
        {
          "name": "limit",
          "type": "integer",
          "required": false,
          "description": "Maximum number of contacts to return (1–500). Defaults to 100."
        },
        {
          "name": "offset",
          "type": "integer",
          "required": false,
          "description": "Number of contacts to skip for pagination. Defaults to 0."
        }
      ],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/contacts/get-many-contacts.md"
    },
    {
      "name": "delete_contact",
      "title": "Delete Contact",
      "category": "Contacts",
      "description": "Deletes a lemlist contact by id or email. Cascades to leads, opportunities, lists, inbox and activities.",
      "method": "DELETE",
      "path": "/contacts/{idOrEmail}",
      "path_params": [
        "idOrEmail"
      ],
      "query_params": [],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/contacts/delete-contact.md"
    },
    {
      "name": "merge_contacts",
      "title": "Merge Contacts",
      "category": "Contacts",
      "description": "Merges up to 10 lemlist contacts into one survivor, moving everything attached to the deleted contacts onto it.",
      "method": "POST",
      "path": "/contacts/merge",
      "path_params": [],
      "query_params": [],
      "body_content_type": "application/json",
      "body_required": true,
      "body_properties": [
        {
          "name": "primaryId",
          "type": "string",
          "required": true,
          "description": "The surviving contact. A lemlist contact id (`ctc_xxx`) or one of the contact's email addresses."
        },
        {
          "name": "secondaryIds",
          "type": "array",
          "required": true,
          "description": "The contacts folded into the survivor then deleted, 9 at most. A lemlist contact id (`ctc_xxx`) or one of the contact's email addresses. Must not contain `primaryId`, and each contact is listed once."
        }
      ],
      "source": "https://developer.lemlist.com/api-reference/endpoints/contacts/merge-contacts.md"
    },
    {
      "name": "get_contact_lists",
      "title": "Get Contact Lists",
      "category": "Contacts",
      "description": "Retrieves all contact lists for the team, with optional name filtering.",
      "method": "GET",
      "path": "/contacts/lists",
      "path_params": [],
      "query_params": [
        {
          "name": "search",
          "type": "string",
          "required": false,
          "description": "Filter lists by name (case-insensitive partial match)."
        }
      ],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/contacts/get-contact-lists.md"
    },
    {
      "name": "create_contact_list",
      "title": "Create Contact List",
      "category": "Contacts",
      "description": "Creates a new static contact list.",
      "method": "POST",
      "path": "/contacts/lists",
      "path_params": [],
      "query_params": [],
      "body_content_type": "application/json",
      "body_required": true,
      "body_properties": [
        {
          "name": "name",
          "type": "string",
          "required": true,
          "description": "Name of the contact list to create (max 200 characters). Cannot contain `<` or `>`."
        }
      ],
      "source": "https://developer.lemlist.com/api-reference/endpoints/contacts/create-contact-list.md"
    },
    {
      "name": "add_or_remove_contacts_in_a_list",
      "title": "Add or Remove Contacts in a List",
      "category": "Contacts",
      "description": "Add contacts to a static contact list, or remove them with ?action=remove.",
      "method": "POST",
      "path": "/contacts/lists/{listId}/entities",
      "path_params": [
        "listId"
      ],
      "query_params": [
        {
          "name": "action",
          "type": "string",
          "required": false,
          "description": "Omit to **add** the contacts to the list. Set to `remove` to **remove** them from the list."
        }
      ],
      "body_content_type": "application/json",
      "body_required": true,
      "body_properties": [
        {
          "name": "contactIds",
          "type": "array",
          "required": true,
          "description": "Array of contact IDs (`ctc_xxx` format) to add to or remove from the list. Required, non-empty, maximum 1,000 per request."
        }
      ],
      "source": "https://developer.lemlist.com/api-reference/endpoints/contacts/manage-contact-list-entities.md"
    },
    {
      "name": "export_contact_list",
      "title": "Export Contact List",
      "category": "Contacts",
      "description": "Exports contacts or companies from a CRM list as a CSV file.",
      "method": "GET",
      "path": "/contacts/export",
      "path_params": [],
      "query_params": [
        {
          "name": "listId",
          "type": "string",
          "required": true,
          "description": "The contact list ID to export (`clt_xxx` format), or `\"all\"` to export all contacts."
        },
        {
          "name": "entity",
          "type": "string",
          "required": false,
          "description": "The type of entities to export. Defaults to `\"contact\"`."
        }
      ],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/contacts/export-contact-list.md"
    },
    {
      "name": "get_many_inboxes",
      "title": "Get Many Inboxes",
      "category": "Inbox",
      "description": "Retrieves all inbox conversations for your team.",
      "method": "GET",
      "path": "/inbox",
      "path_params": [],
      "query_params": [
        {
          "name": "page",
          "type": "integer",
          "required": false,
          "description": "The page number to retrieve"
        },
        {
          "name": "limit",
          "type": "integer",
          "required": false,
          "description": "The maximum number of records to return"
        },
        {
          "name": "userId",
          "type": "string",
          "required": true,
          "description": "Filter by user ID"
        }
      ],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/inbox/get-many-inboxes.md"
    },
    {
      "name": "get_contact_messages",
      "title": "Get Contact Messages",
      "category": "Inbox",
      "description": "Retrieves all messages exchanged with a specific contact.",
      "method": "GET",
      "path": "/inbox/{contactId}",
      "path_params": [
        "contactId"
      ],
      "query_params": [
        {
          "name": "userId",
          "type": "string",
          "required": false,
          "description": "ID of the user viewing the conversation"
        },
        {
          "name": "limit",
          "type": "integer",
          "required": false,
          "description": "The maximum number of records to return"
        },
        {
          "name": "skip",
          "type": "integer",
          "required": false,
          "description": "Number of items to skip. Default: 0"
        },
        {
          "name": "markAsRead",
          "type": "boolean",
          "required": false,
          "description": "When true, marks the conversation as read. Default: false"
        }
      ],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/inbox/get-contact-messages.md"
    },
    {
      "name": "send_email",
      "title": "Send Email",
      "category": "Inbox",
      "description": "Sends an email to a contact through the lemlist inbox. Set replyToActivityId to reply within an existing thread (reuses the thread's subject and CC).",
      "method": "POST",
      "path": "/inbox/email",
      "path_params": [],
      "query_params": [],
      "body_content_type": "application/json",
      "body_required": false,
      "body_properties": [
        {
          "name": "sendUserId",
          "type": "string",
          "required": true,
          "description": "Sender user ID"
        },
        {
          "name": "sendUserEmail",
          "type": "string",
          "required": true,
          "description": "Sender email address"
        },
        {
          "name": "sendUserMailboxId",
          "type": "string",
          "required": true,
          "description": "Sender mailbox ID"
        },
        {
          "name": "contactId",
          "type": "string",
          "required": false,
          "description": "Contact ID. Provide either contactId or leadId (not both required). Returned in the response."
        },
        {
          "name": "leadId",
          "type": "string",
          "required": false,
          "description": "Lead ID. Provide either contactId or leadId; when only leadId is sent, its contact is resolved and returned as contactId in the response."
        },
        {
          "name": "subject",
          "type": "string",
          "required": false,
          "description": "Email subject. Required for a standalone email; on a reply (replyToActivityId set) omit to reuse the thread's subject."
        },
        {
          "name": "message",
          "type": "string",
          "required": true,
          "description": "Email message (HTML)"
        },
        {
          "name": "cc",
          "type": "array",
          "required": false,
          "description": "CC email addresses. On a reply, omit to inherit the thread's CC; pass a list to override, or an empty array to send without CC."
        },
        {
          "name": "replyToActivityId",
          "type": "string",
          "required": false,
          "description": "Reply within an existing email thread. Pass a specific email activity ID (act_...) or \"latest\" for the contact's most recent email. Threads the message (In-Reply-To) and reuses the thread's subject. Omit to send a standalone email. If \"latest\" and the contact has no prior email, a standalone email is sent."
        }
      ],
      "source": "https://developer.lemlist.com/api-reference/endpoints/inbox/send-email.md"
    },
    {
      "name": "send_linkedin_message",
      "title": "Send LinkedIn Message",
      "category": "Inbox",
      "description": "Sends a LinkedIn message to a contact through the lemlist inbox.",
      "method": "POST",
      "path": "/inbox/linkedin",
      "path_params": [],
      "query_params": [],
      "body_content_type": "application/json",
      "body_required": false,
      "body_properties": [
        {
          "name": "sendUserId",
          "type": "string",
          "required": true,
          "description": "Sender user ID"
        },
        {
          "name": "leadId",
          "type": "string",
          "required": true,
          "description": "Lead ID"
        },
        {
          "name": "contactId",
          "type": "string",
          "required": true,
          "description": "Contact ID"
        },
        {
          "name": "message",
          "type": "string",
          "required": true,
          "description": "Message content"
        }
      ],
      "source": "https://developer.lemlist.com/api-reference/endpoints/inbox/send-linkedin-message.md"
    },
    {
      "name": "send_whatsapp_message",
      "title": "Send WhatsApp Message",
      "category": "Inbox",
      "description": "Sends a WhatsApp message to a contact through the lemlist inbox.",
      "method": "POST",
      "path": "/inbox/whatsapp",
      "path_params": [],
      "query_params": [],
      "body_content_type": "application/json",
      "body_required": false,
      "body_properties": [
        {
          "name": "sendUserId",
          "type": "string",
          "required": true,
          "description": "Sender user ID"
        },
        {
          "name": "sendUserWhatsappAccountId",
          "type": "string",
          "required": true,
          "description": "WhatsApp account ID"
        },
        {
          "name": "contactId",
          "type": "string",
          "required": true,
          "description": "Contact ID"
        },
        {
          "name": "leadId",
          "type": "string",
          "required": true,
          "description": "Lead ID"
        },
        {
          "name": "message",
          "type": "string",
          "required": true,
          "description": "Message content"
        }
      ],
      "source": "https://developer.lemlist.com/api-reference/endpoints/inbox/send-whatsapp-message.md"
    },
    {
      "name": "send_sms_message",
      "title": "Send SMS Message",
      "category": "Inbox",
      "description": "Sends an SMS message to a contact through the lemlist inbox.",
      "method": "POST",
      "path": "/inbox/sms",
      "path_params": [],
      "query_params": [],
      "body_content_type": "application/json",
      "body_required": false,
      "body_properties": [
        {
          "name": "sendUserId",
          "type": "string",
          "required": true,
          "description": "Sender user ID. Must belong to the team owning the API key."
        },
        {
          "name": "from",
          "type": "string",
          "required": true,
          "description": "Sender phone number, in E.164 format. Must be a phone number provisioned on your team; an unknown, pending or deleted number fails with `Failed to send SMS`."
        },
        {
          "name": "contactId",
          "type": "string",
          "required": false,
          "description": "Contact ID. Provide either contactId or leadId (not both required). Returned in the response."
        },
        {
          "name": "leadId",
          "type": "string",
          "required": false,
          "description": "Lead ID. Provide either contactId or leadId; when only leadId is sent, its contact is resolved and returned as contactId in the response."
        },
        {
          "name": "message",
          "type": "string",
          "required": true,
          "description": "SMS body. lemlist variables such as {{firstName}} are resolved against the contact before sending, and the resolved message must not be empty."
        }
      ],
      "source": "https://developer.lemlist.com/api-reference/endpoints/inbox/send-sms-message.md"
    },
    {
      "name": "get_many_labels",
      "title": "Get Many Labels",
      "category": "Inbox",
      "description": "List all labels available to your team.",
      "method": "GET",
      "path": "/inbox/labels",
      "path_params": [],
      "query_params": [],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/inbox/get-many-labels.md"
    },
    {
      "name": "get_label",
      "title": "Get Label",
      "category": "Inbox",
      "description": "Get info of a specific label.",
      "method": "GET",
      "path": "/inbox/labels/{labelId}",
      "path_params": [
        "labelId"
      ],
      "query_params": [],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/inbox/get-label.md"
    },
    {
      "name": "create_label",
      "title": "Create Label",
      "category": "Inbox",
      "description": "Creates a new label available to the team.",
      "method": "POST",
      "path": "/inbox/labels",
      "path_params": [],
      "query_params": [],
      "body_content_type": "application/json",
      "body_required": false,
      "body_properties": [
        {
          "name": "labelName",
          "type": "string",
          "required": true,
          "description": "Name of the label to create"
        }
      ],
      "source": "https://developer.lemlist.com/api-reference/endpoints/inbox/create-label.md"
    },
    {
      "name": "attach_labels_to_conversations",
      "title": "Attach Labels to Conversations",
      "category": "Inbox",
      "description": "Attaches one or more labels to one or more conversations.",
      "method": "POST",
      "path": "/inbox/conversations/labels/{contactId}",
      "path_params": [
        "contactId"
      ],
      "query_params": [],
      "body_content_type": "application/json",
      "body_required": false,
      "body_properties": [
        {
          "name": "labelIds",
          "type": "array",
          "required": true,
          "description": "Array of label IDs to attach"
        },
        {
          "name": "appendLabels",
          "type": "boolean",
          "required": true,
          "description": "If true, appends labels to existing ones. If false, replaces all labels."
        }
      ],
      "source": "https://developer.lemlist.com/api-reference/endpoints/inbox/attach-labels-to-conversations.md"
    },
    {
      "name": "remove_labels_from_conversation",
      "title": "Remove Labels from Conversation",
      "category": "Inbox",
      "description": "Removes one or more labels from one conversation.",
      "method": "DELETE",
      "path": "/inbox/conversations/labels/{contactId}",
      "path_params": [
        "contactId"
      ],
      "query_params": [],
      "body_content_type": "application/json",
      "body_required": false,
      "body_properties": [
        {
          "name": "labelIds",
          "type": "array",
          "required": true,
          "description": "Array of label IDs to remove"
        }
      ],
      "source": "https://developer.lemlist.com/api-reference/endpoints/inbox/remove-labels-from-conversation.md"
    },
    {
      "name": "list_drafts",
      "title": "List Drafts",
      "category": "Inbox",
      "description": "Lists all non-deleted drafts for a specific contact.",
      "method": "GET",
      "path": "/inbox/{contactId}/drafts",
      "path_params": [
        "contactId"
      ],
      "query_params": [
        {
          "name": "draftOwner",
          "type": "string",
          "required": true,
          "description": "Draft owner identifier. Accepts either a userId (e.g., `usr_abc123def456789`) or a login email (e.g., `john@acme.com`)."
        }
      ],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/inbox/list-drafts.md"
    },
    {
      "name": "get_draft",
      "title": "Get Draft",
      "category": "Inbox",
      "description": "Retrieves a single draft with its full content, including attachments.",
      "method": "GET",
      "path": "/inbox/{contactId}/drafts/{draftId}",
      "path_params": [
        "contactId",
        "draftId"
      ],
      "query_params": [
        {
          "name": "draftOwner",
          "type": "string",
          "required": true,
          "description": "Draft owner identifier. Accepts either a userId (e.g., `usr_abc123def456789`) or a login email (e.g., `john@acme.com`)."
        }
      ],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/inbox/get-draft.md"
    },
    {
      "name": "create_draft",
      "title": "Create Draft",
      "category": "Inbox",
      "description": "Creates a new draft for a specific contact. The source is automatically set to \"api\".",
      "method": "POST",
      "path": "/inbox/{contactId}/drafts",
      "path_params": [
        "contactId"
      ],
      "query_params": [
        {
          "name": "draftOwner",
          "type": "string",
          "required": true,
          "description": "Draft owner identifier. Accepts either a userId (e.g., `usr_abc123def456789`) or a login email (e.g., `john@acme.com`)."
        }
      ],
      "body_content_type": "application/json",
      "body_required": false,
      "body_properties": [
        {
          "name": "channel",
          "type": "string",
          "required": true,
          "description": "Communication channel"
        },
        {
          "name": "content",
          "type": "string",
          "required": true,
          "description": "Draft content (max 30KB)"
        },
        {
          "name": "subject",
          "type": "string",
          "required": false,
          "description": "Draft subject (optional)"
        },
        {
          "name": "cc",
          "type": "array",
          "required": false,
          "description": "CC email addresses (optional)"
        },
        {
          "name": "attachments",
          "type": "array",
          "required": false,
          "description": "File attachments (optional)"
        },
        {
          "name": "replyToActivityId",
          "type": "string",
          "required": false,
          "description": "Activity ID to reply to (optional)"
        },
        {
          "name": "sourceMetadata",
          "type": "object",
          "required": false,
          "description": "Additional metadata (optional)"
        }
      ],
      "source": "https://developer.lemlist.com/api-reference/endpoints/inbox/create-draft.md"
    },
    {
      "name": "update_draft",
      "title": "Update Draft",
      "category": "Inbox",
      "description": "Partially updates an existing draft. Only the provided fields will be updated.",
      "method": "PATCH",
      "path": "/inbox/{contactId}/drafts/{draftId}",
      "path_params": [
        "contactId",
        "draftId"
      ],
      "query_params": [
        {
          "name": "draftOwner",
          "type": "string",
          "required": true,
          "description": "Draft owner identifier. Accepts either a userId (e.g., `usr_abc123def456789`) or a login email (e.g., `john@acme.com`)."
        }
      ],
      "body_content_type": "application/json",
      "body_required": false,
      "body_properties": [
        {
          "name": "subject",
          "type": "string",
          "required": false,
          "description": "Draft subject"
        },
        {
          "name": "cc",
          "type": "array",
          "required": false,
          "description": "CC email addresses"
        },
        {
          "name": "content",
          "type": "string",
          "required": false,
          "description": "Draft content (max 30KB)"
        },
        {
          "name": "attachments",
          "type": "array",
          "required": false,
          "description": "File attachments"
        },
        {
          "name": "replyToActivityId",
          "type": "string",
          "required": false,
          "description": "Activity ID to reply to"
        }
      ],
      "source": "https://developer.lemlist.com/api-reference/endpoints/inbox/update-draft.md"
    },
    {
      "name": "delete_draft",
      "title": "Delete Draft",
      "category": "Inbox",
      "description": "Soft-deletes a draft by setting its deletedAt timestamp.",
      "method": "DELETE",
      "path": "/inbox/{contactId}/drafts/{draftId}",
      "path_params": [
        "contactId",
        "draftId"
      ],
      "query_params": [
        {
          "name": "draftOwner",
          "type": "string",
          "required": true,
          "description": "Draft owner identifier. Accepts either a userId (e.g., `usr_abc123def456789`) or a login email (e.g., `john@acme.com`)."
        }
      ],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/inbox/delete-draft.md"
    },
    {
      "name": "create_task",
      "title": "Create Task",
      "category": "Tasks",
      "description": "Create a manual task (opportunity) associated with a contact/company or lead.",
      "method": "POST",
      "path": "/tasks",
      "path_params": [],
      "query_params": [],
      "body_content_type": "application/json",
      "body_required": false,
      "body_properties": [
        {
          "name": "recordId",
          "type": "string",
          "required": false,
          "description": "ID of the record the task is about: a contact (`ctc_`), a company (`cpn_`) or a lead (`lea_`). Required unless the legacy `leadId` is sent. A company task can only be of type `manual`."
        },
        {
          "name": "leadId",
          "type": "string",
          "required": false,
          "description": "Legacy name of `recordId`, still accepted for backward compatibility. Use `recordId` instead. When both are sent, `leadId` is used."
        },
        {
          "name": "type",
          "type": "string",
          "required": true,
          "description": "The type of task."
        },
        {
          "name": "assignedTo",
          "type": "string",
          "required": true,
          "description": "The ID of the team member assigned to the task (userId)."
        },
        {
          "name": "dueDate",
          "type": "string",
          "required": true,
          "description": "The due date in ISO 8601 format (e.g., 2025-02-12T00:00:00.000Z). A date in the past is accepted: the task is created already due."
        },
        {
          "name": "title",
          "type": "string",
          "required": false,
          "description": "Optional title of the task. Defaults to an empty string if omitted."
        },
        {
          "name": "message",
          "type": "string",
          "required": false,
          "description": "Optional instruction of the task, returned as `content` in the response. Defaults to an empty string if omitted. On a `linkedin` task for a lead (`lea_` ID), it also pre-fills the draft when `taskData.content` is omitted."
        },
        {
          "name": "taskData",
          "type": "object",
          "required": false,
          "description": "Draft of the message to send on `email`, `linkedin` and `whatsapp` tasks, and fallback number on `phone` tasks."
        },
        {
          "name": "priority",
          "type": "string",
          "required": false,
          "description": "Priority level of the task."
        },
        {
          "name": "images",
          "type": "array",
          "required": false,
          "description": "Public HTTPS URLs of images to attach to a `linkedin` task. lemlist downloads each file and re-hosts it. On other types they are not downloaded, but still count toward the limit of 6. Allowed MIME types: `image/png`, `image/jpeg`, `image/gif`. Up to 20 MB per file, and up to 6 items total combined with `videos`."
        },
        {
          "name": "videos",
          "type": "array",
          "required": false,
          "description": "Public HTTPS URLs of videos to attach to a `linkedin` task. lemlist downloads each file and re-hosts it. On other types they are not downloaded, but still count toward the limit of 6. Allowed MIME types: `video/mp4`, `video/quicktime`. Up to 20 MB per file, and up to 6 items total combined with `images`."
        }
      ],
      "source": "https://developer.lemlist.com/api-reference/endpoints/tasks/create-task.md"
    },
    {
      "name": "search_tasks",
      "title": "Search Tasks",
      "category": "Tasks",
      "description": "Searches your team's tasks with the filters of the Tasks page, and returns every status.",
      "method": "GET",
      "path": "/v2/tasks",
      "path_params": [],
      "query_params": [
        {
          "name": "taskId",
          "type": "string",
          "required": false,
          "description": "Task ids. At most 100. Several values (comma-separated or repeated) are OR-ed."
        },
        {
          "name": "contactId",
          "type": "string",
          "required": false,
          "description": "Contact ids. A single id also matches the tasks of that contact's leads, exactly like the contact panel does. Several values (comma-separated or repeated) are OR-ed."
        },
        {
          "name": "contactIdNot",
          "type": "string",
          "required": false,
          "description": "Excludes the given `contactId` values."
        },
        {
          "name": "companyId",
          "type": "string",
          "required": false,
          "description": "Company ids. Matches company-level tasks AND tasks on that company's contacts. Several values (comma-separated or repeated) are OR-ed."
        },
        {
          "name": "companyIdNot",
          "type": "string",
          "required": false,
          "description": "Excludes the given `companyId` values."
        },
        {
          "name": "leadId",
          "type": "string",
          "required": false,
          "description": "Lead ids. Several values (comma-separated or repeated) are OR-ed."
        },
        {
          "name": "leadIdNot",
          "type": "string",
          "required": false,
          "description": "Excludes the given `leadId` values."
        },
        {
          "name": "campaignId",
          "type": "string",
          "required": false,
          "description": "Campaign ids. Several values (comma-separated or repeated) are OR-ed."
        },
        {
          "name": "campaignIdNot",
          "type": "string",
          "required": false,
          "description": "Excludes the given `campaignId` values."
        },
        {
          "name": "assignedTo",
          "type": "string",
          "required": false,
          "description": "Ids of the users the task is assigned to. Several values (comma-separated or repeated) are OR-ed."
        },
        {
          "name": "assignedToNot",
          "type": "string",
          "required": false,
          "description": "Excludes the given `assignedTo` values."
        },
        {
          "name": "objectType",
          "type": "string",
          "required": false,
          "description": "Restricts to the tasks hanging off a contact (a `contactId` or a `leadId` is present) or off a company (a `companyId` with no contact and no lead). Derived from the ids, never stored."
        },
        {
          "name": "type",
          "type": "string",
          "required": false,
          "description": "Raw step types, comma-separated. This is the same vocabulary as v1 `type`."
        },
        {
          "name": "typeNot",
          "type": "string",
          "required": false,
          "description": "Excludes the given `type` values."
        },
        {
          "name": "channel",
          "type": "string",
          "required": false,
          "description": "Channel the task belongs to — the coarser nomenclature shown in the app as \"Task type\"."
        },
        {
          "name": "status",
          "type": "string",
          "required": false,
          "description": "Task statuses, comma-separated. `pending` is an alias for `due,upcoming,paused`. Unlike v1, completed tasks are returned unless you filter them out."
        },
        {
          "name": "priority",
          "type": "string",
          "required": false,
          "description": "Task priorities (integers), comma-separated."
        },
        {
          "name": "title",
          "type": "string",
          "required": false,
          "description": "Matches tasks whose title contains this text."
        },
        {
          "name": "contactLinkedinUrl",
          "type": "string",
          "required": false,
          "description": "Matches tasks whose contact's LinkedIn URL contains this text. v1's `linkedin` filter matched the lead's URL instead."
        },
        {
          "name": "dueDateFrom",
          "type": "string",
          "required": false,
          "description": "Lower bound of the due date, inclusive. ISO-8601."
        },
        {
          "name": "dueDateTo",
          "type": "string",
          "required": false,
          "description": "Upper bound of the due date, inclusive. ISO-8601."
        },
        {
          "name": "completedAtFrom",
          "type": "string",
          "required": false,
          "description": "Lower bound of the completion date (done or ignored), inclusive. ISO-8601."
        },
        {
          "name": "completedAtTo",
          "type": "string",
          "required": false,
          "description": "Upper bound of the completion date (done or ignored), inclusive. ISO-8601."
        },
        {
          "name": "hasCampaign",
          "type": "boolean",
          "required": false,
          "description": "Restricts to the tasks attached to a campaign (`true`) or to the standalone ones (`false`)."
        },
        {
          "name": "hasDueDate",
          "type": "boolean",
          "required": false,
          "description": "Restricts to the tasks carrying a due date (`true`) or to those without one (`false`)."
        },
        {
          "name": "search",
          "type": "string",
          "required": false,
          "description": "Free-text search over the task title and the contact / company text fields."
        },
        {
          "name": "advancedFilters",
          "type": "string",
          "required": false,
          "description": "A filter tree encoded as JSON, addressing any field returned by `GET /v2/tasks/filters`. Max depth 5, max 50 conditions."
        },
        {
          "name": "include",
          "type": "string",
          "required": false,
          "description": "Embeds the denormalized objects already carried by the task. Comma-separated."
        },
        {
          "name": "sortBy",
          "type": "string",
          "required": false,
          "description": "Field to sort on."
        },
        {
          "name": "sortOrder",
          "type": "string",
          "required": false,
          "description": "Sort direction."
        },
        {
          "name": "page",
          "type": "integer",
          "required": false,
          "description": "Page number, 1-based. `page * limit` must not exceed 10000."
        },
        {
          "name": "limit",
          "type": "integer",
          "required": false,
          "description": "Page size."
        }
      ],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/tasks/get-many-tasks-v2.md"
    },
    {
      "name": "list_task_filters",
      "title": "List Task Filters",
      "category": "Tasks",
      "description": "Lists every field you can use in the advancedFilters tree of Search Tasks.",
      "method": "GET",
      "path": "/v2/tasks/filters",
      "path_params": [],
      "query_params": [
        {
          "name": "scope",
          "type": "string",
          "required": false,
          "description": "Restricts the response to one section."
        },
        {
          "name": "search",
          "type": "string",
          "required": false,
          "description": "Keeps the fields whose id or label contains this text."
        }
      ],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/tasks/get-task-filters.md"
    },
    {
      "name": "get_many_tasks",
      "title": "Get Many Tasks",
      "category": "Tasks",
      "description": "Retrieves all pending tasks assigned to your team members.",
      "method": "GET",
      "path": "/tasks",
      "path_params": [],
      "query_params": [
        {
          "name": "page",
          "type": "integer",
          "required": false,
          "description": "Page number for paginated results (0-indexed)."
        },
        {
          "name": "filters",
          "type": "string",
          "required": false,
          "description": "JSON array of filter objects. Each filter has a `filterId` and specific parameters.\n\n**Available Filters:**\n\n- `fullName`: Filter by contact's full name.\n  - Parameters: `value` (string) or `regex` (string)\n  - Example: `{\"filterId\":\"fullName\",\"value\":\"John Doe\"}`\n\n- `email`: Filter by contact's email address.\n  - Parameters: `value` (string) or `regex` (string)\n  - Example: `{\"filterId\":\"email\",\"value\":\"john@example.com\"}`\n\n- `phone`: Filter by contact's phone number.\n  - Parameters: `value` (s"
        }
      ],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/tasks/get-many-tasks.md"
    },
    {
      "name": "update_task",
      "title": "Update Task",
      "category": "Tasks",
      "description": "Modifies aspects of an existing task including assignment, scheduling, and status.",
      "method": "PATCH",
      "path": "/tasks",
      "path_params": [],
      "query_params": [],
      "body_content_type": "application/json",
      "body_required": false,
      "body_properties": [
        {
          "name": "id",
          "type": "string",
          "required": true,
          "description": "The unique identifier of the task to update"
        },
        {
          "name": "assignedTo",
          "type": "string",
          "required": false,
          "description": "The ID of the team member to assign the task to (userId)"
        },
        {
          "name": "dueDate",
          "type": "string",
          "required": false,
          "description": "Updated due date in ISO 8601 format"
        },
        {
          "name": "title",
          "type": "string",
          "required": false,
          "description": "Updated task title"
        },
        {
          "name": "message",
          "type": "string",
          "required": false,
          "description": "Updated task message/description"
        },
        {
          "name": "priority",
          "type": "string",
          "required": false,
          "description": "Priority level of the task"
        },
        {
          "name": "done",
          "type": "boolean",
          "required": false,
          "description": "Mark task as completed"
        },
        {
          "name": "images",
          "type": "array",
          "required": false,
          "description": "Public HTTPS URLs of images to attach to a LinkedIn task. Replaces the task's current images — pass an empty array to clear them. Returns `400` (`LINKEDIN_MEDIA_INVALID_TYPE`) when the target task is not a LinkedIn task. Allowed MIME types: `image/png`, `image/jpeg`, `image/gif`. Up to 20 MB per file, and up to 6 items total combined with `videos`."
        },
        {
          "name": "videos",
          "type": "array",
          "required": false,
          "description": "Public HTTPS URLs of videos to attach to a LinkedIn task. Replaces the task's current videos — pass an empty array to clear them. Returns `400` (`LINKEDIN_MEDIA_INVALID_TYPE`) when the target task is not a LinkedIn task. Allowed MIME types: `video/mp4`, `video/quicktime`. Up to 20 MB per file, and up to 6 items total combined with `images`."
        }
      ],
      "source": "https://developer.lemlist.com/api-reference/endpoints/tasks/update-task.md"
    },
    {
      "name": "ignore_tasks",
      "title": "Ignore Tasks",
      "category": "Tasks",
      "description": "Marks one or more tasks as ignored.",
      "method": "POST",
      "path": "/tasks/ignore",
      "path_params": [],
      "query_params": [],
      "body_content_type": "application/json",
      "body_required": false,
      "body_properties": [
        {
          "name": "ids",
          "type": "array",
          "required": true,
          "description": "Array of task IDs to ignore"
        }
      ],
      "source": "https://developer.lemlist.com/api-reference/endpoints/tasks/ignore-tasks.md"
    },
    {
      "name": "get_many_activities",
      "title": "Get Many Activities",
      "category": "Activities",
      "description": "Retrieves the history of all campaign activities and steps performed (optionally filtered by activity type and campaign).",
      "method": "GET",
      "path": "/activities",
      "path_params": [],
      "query_params": [
        {
          "name": "version",
          "type": "string",
          "required": true,
          "description": "API version. v2 is mandatory"
        },
        {
          "name": "type",
          "type": "string",
          "required": false,
          "description": "Filter by activity type. Accepts any value from the `ActivityType` enum — mind the exact spelling (email types are plural `emails*`, invites are `linkedinInvite*`). An unknown type returns 400."
        },
        {
          "name": "campaignId",
          "type": "string",
          "required": false,
          "description": "Filter by campaign ID"
        },
        {
          "name": "isFirst",
          "type": "boolean",
          "required": false,
          "description": "Filter for first activity"
        },
        {
          "name": "offset",
          "type": "integer",
          "required": false,
          "description": "Number of records to skip. Note: This is not traditional cursor-based pagination. To retrieve all activities, increment offset by the limit value on each request (e.g., offset=0, then offset=100, then offset=200, etc.)."
        },
        {
          "name": "limit",
          "type": "integer",
          "required": false,
          "description": "Number of activities to retrieve. Default: 100. Maximum: 100"
        },
        {
          "name": "leadId",
          "type": "string",
          "required": false,
          "description": "Filter by lead ID"
        },
        {
          "name": "minDate",
          "type": "string",
          "required": false,
          "description": "Filter activities by `createdAt >= minDate`. Accepts either a Unix timestamp in seconds (e.g. `1715385600`) or an ISO 8601 datetime (e.g. `2026-05-11T00:00:00Z`). `minDate` is the primary name; `startDate` is accepted as an alias and `minDate` takes precedence when both are provided."
        },
        {
          "name": "maxDate",
          "type": "string",
          "required": false,
          "description": "Filter activities by `createdAt <= maxDate`. Accepts either a Unix timestamp in seconds (e.g. `1715385600`) or an ISO 8601 datetime (e.g. `2026-05-11T00:00:00Z`). Must be strictly greater than `minDate` when both are provided. `maxDate` is the primary name; `endDate` is accepted as an alias and `maxDate` takes precedence when both are provided."
        },
        {
          "name": "startDate",
          "type": "string",
          "required": false,
          "description": "Alias for `minDate`, provided for consistency with sibling endpoints (e.g. `/campaigns/{campaignId}/stats`). Accepts either a Unix timestamp in seconds or an ISO 8601 datetime. Ignored when `minDate` is also provided."
        },
        {
          "name": "endDate",
          "type": "string",
          "required": false,
          "description": "Alias for `maxDate`, provided for consistency with sibling endpoints (e.g. `/campaigns/{campaignId}/stats`). Accepts either a Unix timestamp in seconds or an ISO 8601 datetime. Ignored when `maxDate` is also provided."
        }
      ],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/activities/get-many-activities.md"
    },
    {
      "name": "delete_activity_recording_transcript",
      "title": "Delete Activity Recording & Transcript",
      "category": "Activities",
      "description": "Deletes the call recording and transcript associated with an activity.",
      "method": "DELETE",
      "path": "/activities/{activityId}/recording-transcript",
      "path_params": [
        "activityId"
      ],
      "query_params": [],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/activities/delete-activity-recording-transcript.md"
    },
    {
      "name": "get_team_crm_users",
      "title": "Get Team CRM Users",
      "category": "Team",
      "description": "Retrieves the team members whose CRM account is connected to lemlist.",
      "method": "GET",
      "path": "/team/crmUsers",
      "path_params": [],
      "query_params": [],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/crm/get-team-crm-users.md"
    },
    {
      "name": "get_crm_filters",
      "title": "Get CRM Filters",
      "category": "Leads",
      "description": "Retrieves the filters of your team's connected CRM that leads can be imported from.",
      "method": "GET",
      "path": "/crm/filters",
      "path_params": [],
      "query_params": [
        {
          "name": "type",
          "type": "string",
          "required": false,
          "description": "Salesforce only: `lead` or `contact` list views, or `report`. Ignored by HubSpot and Pipedrive. Defaults to `lead` when your Salesforce connection allows Leads, `contact` otherwise."
        }
      ],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/crm/get-crm-filters.md"
    },
    {
      "name": "list_unsubscribed_variables",
      "title": "List Unsubscribed Variables",
      "category": "Unsubscribes",
      "description": "Retrieves a paginated list of all unsubscribed variables (emails, domains, LinkedIn URLs, phone numbers).",
      "method": "GET",
      "path": "/v2/unsubscribes/variables",
      "path_params": [],
      "query_params": [
        {
          "name": "offset",
          "type": "integer",
          "required": false,
          "description": "Number of entries to skip for pagination"
        },
        {
          "name": "limit",
          "type": "integer",
          "required": false,
          "description": "Number of entries to return (max 100)"
        }
      ],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/unsubscribes/list-unsubscribed-variables.md"
    },
    {
      "name": "get_unsubscribed_variable",
      "title": "Get Unsubscribed Variable",
      "category": "Unsubscribes",
      "description": "Retrieves a specific unsubscribed variable by its value.",
      "method": "GET",
      "path": "/v2/unsubscribes/variables/{value}",
      "path_params": [
        "value"
      ],
      "query_params": [],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/unsubscribes/get-unsubscribed-variable.md"
    },
    {
      "name": "unsubscribe_variable",
      "title": "Unsubscribe Variable",
      "category": "Unsubscribes",
      "description": "Unsubscribes a single variable. Idempotent — returns the existing record if already unsubscribed.",
      "method": "POST",
      "path": "/v2/unsubscribes/variables/{value}",
      "path_params": [
        "value"
      ],
      "query_params": [],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/unsubscribes/unsubscribe-variable.md"
    },
    {
      "name": "bulk_unsubscribe_variables",
      "title": "Bulk Unsubscribe Variables",
      "category": "Unsubscribes",
      "description": "Unsubscribes up to 10,000 variables in a single request.",
      "method": "POST",
      "path": "/v2/unsubscribes/variables",
      "path_params": [],
      "query_params": [],
      "body_content_type": "application/json",
      "body_required": true,
      "body_properties": [
        {
          "name": "values",
          "type": "array",
          "required": true,
          "description": "List of variables to unsubscribe (emails, domains, LinkedIn URLs, or phone numbers). Maximum 10,000 values."
        }
      ],
      "source": "https://developer.lemlist.com/api-reference/endpoints/unsubscribes/bulk-unsubscribe-variables.md"
    },
    {
      "name": "re_subscribe_variable",
      "title": "Re-subscribe Variable",
      "category": "Unsubscribes",
      "description": "Re-subscribes a variable, removing it from the unsubscribe list.",
      "method": "DELETE",
      "path": "/v2/unsubscribes/variables/{value}",
      "path_params": [
        "value"
      ],
      "query_params": [],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/unsubscribes/resubscribe-variable.md"
    },
    {
      "name": "export_unsubscribed_variables",
      "title": "Export Unsubscribed Variables",
      "category": "Unsubscribes",
      "description": "Exports all unsubscribed variables as CSV (default) or JSON.",
      "method": "GET",
      "path": "/v2/unsubscribes/exports/variables",
      "path_params": [],
      "query_params": [
        {
          "name": "format",
          "type": "string",
          "required": false,
          "description": "Output format: 'json' or 'csv'. Default is CSV."
        }
      ],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/unsubscribes/export-unsubscribed-variables.md"
    },
    {
      "name": "get_contact_subscription_status",
      "title": "Get Contact Subscription Status",
      "category": "Unsubscribes",
      "description": "Checks whether a contact is unsubscribed (do-not-contact).",
      "method": "GET",
      "path": "/v2/unsubscribes/contacts/{contactId}",
      "path_params": [
        "contactId"
      ],
      "query_params": [],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/unsubscribes/get-contact-subscription-status.md"
    },
    {
      "name": "unsubscribe_contact",
      "title": "Unsubscribe Contact",
      "category": "Unsubscribes",
      "description": "Marks a contact as unsubscribed (do-not-contact).",
      "method": "POST",
      "path": "/v2/unsubscribes/contacts/{contactId}",
      "path_params": [
        "contactId"
      ],
      "query_params": [],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/unsubscribes/unsubscribe-contact.md"
    },
    {
      "name": "re_subscribe_contact",
      "title": "Re-subscribe Contact",
      "category": "Unsubscribes",
      "description": "Re-subscribes a contact, removing the do-not-contact flag.",
      "method": "DELETE",
      "path": "/v2/unsubscribes/contacts/{contactId}",
      "path_params": [
        "contactId"
      ],
      "query_params": [],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/unsubscribes/resubscribe-contact.md"
    },
    {
      "name": "export_unsubscribed_contacts",
      "title": "Export Unsubscribed Contacts",
      "category": "Unsubscribes",
      "description": "Exports all contacts with their subscription status as CSV (default) or JSON.",
      "method": "GET",
      "path": "/v2/unsubscribes/exports/contacts",
      "path_params": [],
      "query_params": [
        {
          "name": "format",
          "type": "string",
          "required": false,
          "description": "Output format: 'json' or 'csv'. Default is CSV."
        }
      ],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/unsubscribes/export-unsubscribed-contacts.md"
    },
    {
      "name": "add_unsubscribe_email_or_domain",
      "title": "Add Unsubscribe Email or Domain",
      "category": "Unsubscribes",
      "description": "Adds an email address or domain to your unsubscribe list.",
      "method": "POST",
      "path": "/unsubscribes/{email}",
      "path_params": [
        "email"
      ],
      "query_params": [],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/unsubscribes/add-unsubscribe-email-or-domain.md"
    },
    {
      "name": "get_unsubscribe_by_email",
      "title": "Get Unsubscribe by Email",
      "category": "Unsubscribes",
      "description": "Retrieves unsubscribe information for a specific email address.",
      "method": "GET",
      "path": "/unsubscribes/{email}",
      "path_params": [
        "email"
      ],
      "query_params": [],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/unsubscribes/get-unsubscribe-by-email.md"
    },
    {
      "name": "get_many_unsubscribes",
      "title": "Get Many Unsubscribes",
      "category": "Unsubscribes",
      "description": "Retrieves a list of all unsubscribed emails and domains.",
      "method": "GET",
      "path": "/unsubscribes",
      "path_params": [],
      "query_params": [
        {
          "name": "offset",
          "type": "integer",
          "required": false,
          "description": "Offset for pagination"
        },
        {
          "name": "limit",
          "type": "integer",
          "required": false,
          "description": "Number of unsubscribes to retrieve. Default: 100"
        }
      ],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/unsubscribes/get-many-unsubscribes.md"
    },
    {
      "name": "delete_unsubscribe_email",
      "title": "Delete Unsubscribe Email",
      "category": "Unsubscribes",
      "description": "Removes an email address from your unsubscribe list.",
      "method": "DELETE",
      "path": "/unsubscribes/{email}",
      "path_params": [
        "email"
      ],
      "query_params": [],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/unsubscribes/delete-unsubscribe-email.md"
    },
    {
      "name": "export_unsubscribes",
      "title": "Export Unsubscribes",
      "category": "Unsubscribes",
      "description": "Exports all unsubscribed emails and domains to a CSV file.",
      "method": "GET",
      "path": "/unsubs/export",
      "path_params": [],
      "query_params": [],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/unsubscribes/export-unsubscribes.md"
    },
    {
      "name": "delete_webhook",
      "title": "Delete Webhook",
      "category": "Webhooks",
      "description": "Deletes a specific webhook.",
      "method": "DELETE",
      "path": "/hooks/{hookId}",
      "path_params": [
        "hookId"
      ],
      "query_params": [],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/webhooks/delete-webhook.md"
    },
    {
      "name": "get_many_webhooks",
      "title": "Get Many Webhooks",
      "category": "Webhooks",
      "description": "Retrieves all webhooks configured for your team.",
      "method": "GET",
      "path": "/hooks",
      "path_params": [],
      "query_params": [],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/webhooks/get-many-webhooks.md"
    },
    {
      "name": "search_companies_database",
      "title": "Search Companies Database",
      "category": "People Database",
      "description": "Searches the companies database using filters, keywords, and pagination.",
      "method": "POST",
      "path": "/database/companies",
      "path_params": [],
      "query_params": [],
      "body_content_type": "application/json",
      "body_required": false,
      "body_properties": [
        {
          "name": "filters",
          "type": "array",
          "required": false,
          "description": "Array of filter objects to narrow down search results. Each filter has a filterId and inclusion/exclusion criteria."
        },
        {
          "name": "page",
          "type": "integer",
          "required": false,
          "description": "Page number for pagination (default: 1)"
        },
        {
          "name": "size",
          "type": "integer",
          "required": false,
          "description": "Number of results per page (default: 100, max: 500)"
        }
      ],
      "source": "https://developer.lemlist.com/api-reference/endpoints/people-database/search-companies-database.md"
    },
    {
      "name": "get_database_filters",
      "title": "Get Database Filters",
      "category": "People Database",
      "description": "Retrieves available filters for searching the people and companies database.",
      "method": "GET",
      "path": "/database/filters",
      "path_params": [],
      "query_params": [],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/people-database/get-database-filters.md"
    },
    {
      "name": "list_personas",
      "title": "List Personas",
      "category": "People Database",
      "description": "Retrieves the People Database personas saved by your team.",
      "method": "GET",
      "path": "/database/personas",
      "path_params": [],
      "query_params": [
        {
          "name": "mode",
          "type": "string",
          "required": false,
          "description": "Restrict the list to personas of one search mode. Omit to return every persona of the team."
        }
      ],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/people-database/list-personas.md"
    },
    {
      "name": "create_persona",
      "title": "Create Persona",
      "category": "People Database",
      "description": "Creates a People Database persona for your team.",
      "method": "POST",
      "path": "/database/personas",
      "path_params": [],
      "query_params": [],
      "body_content_type": "application/json",
      "body_required": true,
      "body_properties": [
        {
          "name": "name",
          "type": "string",
          "required": true,
          "description": "Display name. Non-empty, and unique within your team."
        },
        {
          "name": "filters",
          "type": "array",
          "required": true,
          "description": "People Database filters defining the persona"
        },
        {
          "name": "mode",
          "type": "string",
          "required": true,
          "description": "Search mode the filters target. Only `leads` is accepted today."
        }
      ],
      "source": "https://developer.lemlist.com/api-reference/endpoints/people-database/create-persona.md"
    },
    {
      "name": "delete_persona",
      "title": "Delete Persona",
      "category": "People Database",
      "description": "Deletes a People Database persona.",
      "method": "DELETE",
      "path": "/database/personas/{personaId}",
      "path_params": [
        "personaId"
      ],
      "query_params": [],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/people-database/delete-persona.md"
    },
    {
      "name": "run_contact_sourcing",
      "title": "Run Contact Sourcing",
      "category": "Contact sourcing",
      "description": "Starts an AI contact-sourcing run for one or more accounts.",
      "method": "POST",
      "path": "/contact-sourcing",
      "path_params": [],
      "query_params": [],
      "body_content_type": "application/json",
      "body_required": true,
      "body_properties": [
        {
          "name": "companyIds",
          "type": "array",
          "required": true,
          "description": "Accounts to source contacts for (`cpn_xxx` format)."
        },
        {
          "name": "overwrite",
          "type": "boolean",
          "required": false,
          "description": ""
        }
      ],
      "source": "https://developer.lemlist.com/api-reference/endpoints/contact-sourcing/run-contact-sourcing.md"
    },
    {
      "name": "get_contact_sourcing_run",
      "title": "Get Contact Sourcing Run",
      "category": "Contact sourcing",
      "description": "Reads a contact-sourcing run by ID, or the latest run of an account.",
      "method": "GET",
      "path": "/contact-sourcing",
      "path_params": [],
      "query_params": [
        {
          "name": "runId",
          "type": "string",
          "required": false,
          "description": "The run to read, as returned by `POST /contact-sourcing`."
        },
        {
          "name": "companyId",
          "type": "string",
          "required": false,
          "description": "Read the LATEST run of this account instead (`cpn_xxx` format)."
        }
      ],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/contact-sourcing/get-contact-sourcing-run.md"
    },
    {
      "name": "add_a_sourced_contact",
      "title": "Add a Sourced Contact",
      "category": "Contact sourcing",
      "description": "Turns one contact-sourcing recommendation into a lemlist contact.",
      "method": "POST",
      "path": "/contact-sourcing/contacts",
      "path_params": [],
      "query_params": [],
      "body_content_type": "application/json",
      "body_required": true,
      "body_properties": [
        {
          "name": "leadId",
          "type": "string",
          "required": true,
          "description": "People-Database id, from a run's `contacts[].leadId`."
        },
        {
          "name": "companyId",
          "type": "string",
          "required": true,
          "description": ""
        },
        {
          "name": "listId",
          "type": "string",
          "required": false,
          "description": "File the new contact into this contact list (`clt_xxx`). Omit to leave it in all contacts."
        },
        {
          "name": "findEmail",
          "type": "boolean",
          "required": false,
          "description": "Also run email enrichment on the new contact. Spends enrichment credits."
        }
      ],
      "source": "https://developer.lemlist.com/api-reference/endpoints/contact-sourcing/add-sourced-contact.md"
    },
    {
      "name": "bulk_enrich_data",
      "title": "Bulk Enrich Data",
      "category": "Enrich",
      "description": "Performs batch enrichment for up to 500 entities to find emails, phone numbers, or LinkedIn data.",
      "method": "POST",
      "path": "/v2/enrichments/bulk",
      "path_params": [],
      "query_params": [
        {
          "name": "webhookUrl",
          "type": "string",
          "required": false,
          "description": "Webhook URL for enrichment events"
        }
      ],
      "body_content_type": "application/json",
      "body_required": true,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/enrich/bulk-enrich-data.md"
    },
    {
      "name": "enrich_lead",
      "title": "Enrich Lead",
      "category": "Enrich",
      "description": "Enriches an existing lead in lemlist with additional data.",
      "method": "POST",
      "path": "/leads/{leadId}/enrich",
      "path_params": [
        "leadId"
      ],
      "query_params": [
        {
          "name": "findEmail",
          "type": "boolean",
          "required": false,
          "description": "Search email address in another campaign"
        },
        {
          "name": "verifyEmail",
          "type": "boolean",
          "required": false,
          "description": "Find verified email"
        },
        {
          "name": "linkedinEnrichment",
          "type": "boolean",
          "required": false,
          "description": "Run LinkedIn enrichment"
        },
        {
          "name": "findPhone",
          "type": "boolean",
          "required": false,
          "description": "Find phone number"
        },
        {
          "name": "webhookUrl",
          "type": "string",
          "required": false,
          "description": "Webhook URL for enrichment events"
        },
        {
          "name": "force",
          "type": "boolean",
          "required": false,
          "description": "Re-run an enrichment that would otherwise be skipped. Bypasses skips caused by data already present on the contact: existing email, existing phone, LinkedIn enrichment already done for the same `linkedinUrl` / `linkedinUrlSalesNav`, or email already having a deliverability status.\n\nDoes **not** bypass:\n- **Enrichment currently in progress** — if another enrichment is already running for this contact, the request is still skipped (no parallel enrichments, no double billing).\n- **Previously return"
        }
      ],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/enrich/enrich-lead.md"
    },
    {
      "name": "get_enrichment_result",
      "title": "Get Enrichment Result",
      "category": "Enrich",
      "description": "Retrieves the results of a completed enrichment request.",
      "method": "GET",
      "path": "/enrich/{enrichId}",
      "path_params": [
        "enrichId"
      ],
      "query_params": [],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/enrich/get-enrichment-result.md"
    },
    {
      "name": "list_enrichment_providers",
      "title": "List Enrichment Providers",
      "category": "Enrichment Providers",
      "description": "Lists the enrichment providers your team can place in a waterfall, for one enrichment type.",
      "method": "GET",
      "path": "/v2/enrichments/providers",
      "path_params": [],
      "query_params": [
        {
          "name": "type",
          "type": "string",
          "required": true,
          "description": "Enrichment type of the providers to list."
        }
      ],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/enrichment-providers/list-enrichment-providers.md"
    },
    {
      "name": "connect_provider",
      "title": "Connect Provider",
      "category": "Enrichment Providers",
      "description": "Saves your own API key for an external enrichment provider, connecting it for your waterfalls.",
      "method": "PUT",
      "path": "/v2/enrichments/providers/{providerId}/connection",
      "path_params": [
        "providerId"
      ],
      "query_params": [],
      "body_content_type": "application/json",
      "body_required": true,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/enrichment-providers/connect-provider.md"
    },
    {
      "name": "disconnect_provider",
      "title": "Disconnect Provider",
      "category": "Enrichment Providers",
      "description": "Removes the API key of an external enrichment provider; lemlist stops calling it on your account.",
      "method": "DELETE",
      "path": "/v2/enrichments/providers/{providerId}/connection",
      "path_params": [
        "providerId"
      ],
      "query_params": [],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/enrichment-providers/disconnect-provider.md"
    },
    {
      "name": "list_enrichment_waterfalls",
      "title": "List Enrichment Waterfalls",
      "category": "Enrichment Waterfalls",
      "description": "Lists your team's enrichment waterfalls — the default waterfall of each type, plus every custom waterfall.",
      "method": "GET",
      "path": "/v2/enrichments/waterfalls",
      "path_params": [],
      "query_params": [
        {
          "name": "type",
          "type": "string",
          "required": false,
          "description": "Restrict the list to one enrichment type. Omit to return both."
        }
      ],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/enrichment-waterfalls/list-enrichment-waterfalls.md"
    },
    {
      "name": "get_enrichment_waterfall",
      "title": "Get Enrichment Waterfall",
      "category": "Enrichment Waterfalls",
      "description": "Returns one enrichment waterfall of your team, default or custom.",
      "method": "GET",
      "path": "/v2/enrichments/waterfalls/{waterfallId}",
      "path_params": [
        "waterfallId"
      ],
      "query_params": [],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/enrichment-waterfalls/get-enrichment-waterfall.md"
    },
    {
      "name": "update_enrichment_waterfall",
      "title": "Update Enrichment Waterfall",
      "category": "Enrichment Waterfalls",
      "description": "Updates the name or provider order of an enrichment waterfall.",
      "method": "PATCH",
      "path": "/v2/enrichments/waterfalls/{waterfallId}",
      "path_params": [
        "waterfallId"
      ],
      "query_params": [],
      "body_content_type": "application/json",
      "body_required": true,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/enrichment-waterfalls/update-enrichment-waterfall.md"
    },
    {
      "name": "reset_enrichment_waterfall",
      "title": "Reset Enrichment Waterfall",
      "category": "Enrichment Waterfalls",
      "description": "Hands a default enrichment waterfall back to lemlist, restoring its random provider order.",
      "method": "PUT",
      "path": "/v2/enrichments/waterfalls/{waterfallId}/reset",
      "path_params": [
        "waterfallId"
      ],
      "query_params": [],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/enrichment-waterfalls/reset-enrichment-waterfall.md"
    },
    {
      "name": "start_lemwarm",
      "title": "Start lemwarm",
      "category": "lemwarm",
      "description": "Starts lemwarm email deliverability improvement for a specific user mailbox.",
      "method": "POST",
      "path": "/lemwarm/{userMailboxId}/start",
      "path_params": [
        "userMailboxId"
      ],
      "query_params": [],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/lemwarm/start-lemwarm.md"
    },
    {
      "name": "pause_lemwarm",
      "title": "Pause lemwarm",
      "category": "lemwarm",
      "description": "Pauses lemwarm email deliverability improvement for a specific user mailbox.",
      "method": "POST",
      "path": "/lemwarm/{userMailboxId}/pause",
      "path_params": [
        "userMailboxId"
      ],
      "query_params": [],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/lemwarm/pause-lemwarm.md"
    },
    {
      "name": "get_lemwarm_settings",
      "title": "Get lemwarm Settings",
      "category": "lemwarm",
      "description": "Retrieves lemwarm email deliverability settings for a specific user mailbox.",
      "method": "GET",
      "path": "/lemwarm/{userMailboxId}/settings",
      "path_params": [
        "userMailboxId"
      ],
      "query_params": [],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/lemwarm/get-lemwarm-settings.md"
    },
    {
      "name": "update_lemwarm_settings",
      "title": "Update lemwarm Settings",
      "category": "lemwarm",
      "description": "Updates lemwarm email deliverability settings for a specific user mailbox.",
      "method": "PATCH",
      "path": "/lemwarm/{userMailboxId}/settings",
      "path_params": [
        "userMailboxId"
      ],
      "query_params": [],
      "body_content_type": "application/json",
      "body_required": false,
      "body_properties": [
        {
          "name": "warmEmailMax",
          "type": "integer",
          "required": false,
          "description": "Maximum number of warmup emails per day (0-40; the server enforces 1-40 unless the team has the lemwarm0limit beta)"
        },
        {
          "name": "warmEmailRampup",
          "type": "integer",
          "required": false,
          "description": "Daily increase in the warmup email count (0-40; the server enforces 1-40 unless the team has the lemwarm0limit beta)"
        },
        {
          "name": "internalCommunicationPercent",
          "type": "integer",
          "required": false,
          "description": "Percentage of warmup emails sent to internal participants (0-100)"
        },
        {
          "name": "answerPercentage",
          "type": "integer",
          "required": false,
          "description": "Percentage of warmup emails that should be answered (0-100)"
        },
        {
          "name": "warmUsePlaintext",
          "type": "boolean",
          "required": false,
          "description": "Whether warmup emails are sent as plain text"
        },
        {
          "name": "warmDailyVarianceEnabled",
          "type": "boolean",
          "required": false,
          "description": "Whether to apply a random daily variance to the warmup email target (spreads volume day-to-day instead of a flat number)"
        }
      ],
      "source": "https://developer.lemlist.com/api-reference/endpoints/lemwarm/update-lemwarm-settings.md"
    },
    {
      "name": "list_signal_agents",
      "title": "List Signal Agents",
      "category": "Signal Agents",
      "description": "Retrieves your Signal Agents (watch lists) with pagination and optional filtering by signal type and status.",
      "method": "GET",
      "path": "/watchlist",
      "path_params": [],
      "query_params": [
        {
          "name": "page",
          "type": "integer",
          "required": false,
          "description": "Page number to retrieve"
        },
        {
          "name": "limit",
          "type": "integer",
          "required": false,
          "description": "Number of records to retrieve. Maximum value: 100"
        },
        {
          "name": "type",
          "type": "string",
          "required": false,
          "description": "Filter by signal type(s). Comma-separated list of signal types."
        },
        {
          "name": "status",
          "type": "string",
          "required": false,
          "description": "Filter by lifecycle status(es). Comma-separated list. Defaults to every status except `delete`."
        }
      ],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/watch-list/list-watch-lists.md"
    },
    {
      "name": "create_signal_agent",
      "title": "Create Signal Agent",
      "category": "Signal Agents",
      "description": "Creates a new Signal Agent (watch list).",
      "method": "POST",
      "path": "/watchlist",
      "path_params": [],
      "query_params": [],
      "body_content_type": "application/json",
      "body_required": true,
      "body_properties": [
        {
          "name": "name",
          "type": "string",
          "required": true,
          "description": "Display name"
        },
        {
          "name": "type",
          "type": "string",
          "required": true,
          "description": "Signal type to monitor"
        },
        {
          "name": "filters",
          "type": "array",
          "required": false,
          "description": "Filters to apply (validated against the signal type)"
        },
        {
          "name": "emoji",
          "type": "string",
          "required": false,
          "description": "Emoji shown next to the agent name (defaults to a random emoji)"
        },
        {
          "name": "segmentType",
          "type": "string",
          "required": false,
          "description": "Entity sourcing. Only `all` is supported via the API. Required together with signalProcessingType when activate is true."
        },
        {
          "name": "signalProcessingType",
          "type": "string",
          "required": false,
          "description": "How detected signals are processed"
        },
        {
          "name": "signalOpportunityTemplate",
          "type": "object",
          "required": false,
          "description": "Task/opportunity template applied to each signal when signalProcessingType is create_opportunity."
        },
        {
          "name": "personaId",
          "type": "string",
          "required": false,
          "description": "Persona (pdp_xxx) used to source contacts from the People Database. Only for a company Signal Agent with signalProcessingType = push_to_campaign whose signal type does not already ship its own contact (those company signals carry no contact, so the persona is the only way to know who to reach). Optional; rejected on any other configuration."
        },
        {
          "name": "activate",
          "type": "boolean",
          "required": false,
          "description": "Fully set up and activate the agent. Requires segmentType and signalProcessingType."
        }
      ],
      "source": "https://developer.lemlist.com/api-reference/endpoints/watch-list/create-watch-list.md"
    },
    {
      "name": "update_signal_agent",
      "title": "Update Signal Agent",
      "category": "Signal Agents",
      "description": "Updates an existing Signal Agent (watch list).",
      "method": "PATCH",
      "path": "/watchlist",
      "path_params": [],
      "query_params": [],
      "body_content_type": "application/json",
      "body_required": true,
      "body_properties": [
        {
          "name": "watchListId",
          "type": "string",
          "required": true,
          "description": "Signal Agent id to update"
        },
        {
          "name": "name",
          "type": "string",
          "required": false,
          "description": "New display name"
        },
        {
          "name": "filters",
          "type": "array",
          "required": false,
          "description": "Replacement filters (validated against the agent's signal type)"
        },
        {
          "name": "emoji",
          "type": "string",
          "required": false,
          "description": "New emoji"
        },
        {
          "name": "signalProcessingType",
          "type": "string",
          "required": false,
          "description": "New signal processing type"
        },
        {
          "name": "personaId",
          "type": "string",
          "required": false,
          "description": "Persona (pdp_xxx) used to source contacts from the People Database. Only for a company Signal Agent with signalProcessingType = push_to_campaign whose signal type does not already ship its own contact. Optional; rejected on any other configuration."
        },
        {
          "name": "activate",
          "type": "boolean",
          "required": false,
          "description": "Toggle the agent status. false deactivates (pauses) it immediately. true reactivates a paused agent (triggers billing and external watcher setup). A draft cannot be toggled this way. Omit to leave the status unchanged."
        }
      ],
      "source": "https://developer.lemlist.com/api-reference/endpoints/watch-list/update-watch-list.md"
    },
    {
      "name": "delete_signal_agent",
      "title": "Delete Signal Agent",
      "category": "Signal Agents",
      "description": "Deletes a Signal Agent (watch list).",
      "method": "DELETE",
      "path": "/watchlist",
      "path_params": [],
      "query_params": [
        {
          "name": "watchListId",
          "type": "string",
          "required": true,
          "description": "Signal Agent id to delete"
        }
      ],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/watch-list/delete-watch-list.md"
    },
    {
      "name": "get_signal_agent_configuration_history",
      "title": "Get Signal Agent configuration history",
      "category": "Signal Agents",
      "description": "Retrieves the configuration history of a Signal Agent — each past config version with its active period and stats.",
      "method": "GET",
      "path": "/watchlist/history",
      "path_params": [],
      "query_params": [
        {
          "name": "watchListId",
          "type": "string",
          "required": true,
          "description": "Signal Agent id whose history to fetch"
        },
        {
          "name": "page",
          "type": "integer",
          "required": false,
          "description": "Page number to retrieve"
        },
        {
          "name": "limit",
          "type": "integer",
          "required": false,
          "description": "Number of records to retrieve. Maximum value: 100"
        }
      ],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/watch-list/get-history.md"
    },
    {
      "name": "get_signal_agent_signals",
      "title": "Get Signal Agent signals",
      "category": "Signal Agents",
      "description": "Retrieves paginated signals detected by your Signal Agents with filtering and sorting capabilities.",
      "method": "GET",
      "path": "/watchlist/signals",
      "path_params": [],
      "query_params": [
        {
          "name": "page",
          "type": "integer",
          "required": false,
          "description": "Page number to retrieve"
        },
        {
          "name": "limit",
          "type": "integer",
          "required": false,
          "description": "Number of signals to retrieve. Maximum value: 100"
        },
        {
          "name": "sortBy",
          "type": "string",
          "required": false,
          "description": "The field by which to sort signals"
        },
        {
          "name": "sortOrder",
          "type": "string",
          "required": false,
          "description": "The sort direction"
        },
        {
          "name": "type",
          "type": "string",
          "required": false,
          "description": "Filter by signal type(s). Can be a single value or array using type[] notation. Valid values from WATCH_LIST_SIGNAL_CONFIGURATIONS_TYPES_STANDARD_KEYS"
        },
        {
          "name": "status",
          "type": "string",
          "required": false,
          "description": "Filter by signal status(es). Can be a single value or array using status[] notation. Valid values from WATCH_LIST_SIGNAL_COMPUTED_STATUSES"
        },
        {
          "name": "receivedAtFrom",
          "type": "string",
          "required": false,
          "description": "Filter signals received on or after this date (ISO date string)"
        },
        {
          "name": "receivedAtTo",
          "type": "string",
          "required": false,
          "description": "Filter signals received on or before this date (ISO date string). Must be greater than receivedAtFrom if both are provided"
        },
        {
          "name": "watchListId",
          "type": "string",
          "required": false,
          "description": "Filter signals by specific Signal Agent ID"
        }
      ],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/watch-list/get-signals.md"
    },
    {
      "name": "mark_signals_handled_or_ignored",
      "title": "Mark signals handled or ignored",
      "category": "Signal Agents",
      "description": "Marks one or several signals as handled or ignored.",
      "method": "PUT",
      "path": "/watchlist/signals",
      "path_params": [],
      "query_params": [],
      "body_content_type": "application/json",
      "body_required": true,
      "body_properties": [
        {
          "name": "signalIds",
          "type": "array",
          "required": true,
          "description": "Signal ids (wsi_xxx) to update, from List signals. Between 1 and 1000 per call."
        },
        {
          "name": "status",
          "type": "string",
          "required": true,
          "description": "Target status to set on every signal."
        },
        {
          "name": "reason",
          "type": "string",
          "required": false,
          "description": "Optional note explaining the decision. Only meaningful when status is \"ignored\"."
        }
      ],
      "source": "https://developer.lemlist.com/api-reference/endpoints/watch-list/mark-signals.md"
    },
    {
      "name": "push_external_signals",
      "title": "Push external signals",
      "category": "Signal Agents",
      "description": "Pushes a contact- or company-level external signal into a Signal Agent.",
      "method": "POST",
      "path": "/watchlist/{watchListId}/external-signals",
      "path_params": [
        "watchListId"
      ],
      "query_params": [],
      "body_content_type": "application/json",
      "body_required": true,
      "body_properties": [
        {
          "name": "contact",
          "type": "object",
          "required": false,
          "description": "The contact the signal is about. Required for externalSignalContact agents; ignored otherwise."
        },
        {
          "name": "company",
          "type": "object",
          "required": false,
          "description": "The company the signal is about. Required for externalSignalCompany agents; ignored otherwise."
        },
        {
          "name": "customFields",
          "type": "object",
          "required": false,
          "description": "Optional key/value metadata stored on the signal. Max 20 keys; all values must be strings."
        }
      ],
      "source": "https://developer.lemlist.com/api-reference/endpoints/watch-list/push-external-signals.md"
    },
    {
      "name": "list_available_signal_types",
      "title": "List available signal types",
      "category": "Signal Agents",
      "description": "Lists the signal types available to your team, each with a title and description.",
      "method": "GET",
      "path": "/watchlist/library",
      "path_params": [],
      "query_params": [],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/watch-list/get-library.md"
    },
    {
      "name": "list_allowed_filters_per_signal_type",
      "title": "List allowed filters per signal type",
      "category": "Signal Agents",
      "description": "Lists, per signal type, the filters you can set on a Signal Agent.",
      "method": "GET",
      "path": "/watchlist/filters",
      "path_params": [],
      "query_params": [
        {
          "name": "type",
          "type": "string",
          "required": false,
          "description": "Restrict the response to a single signal type. Omit to return filters for every type."
        }
      ],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/watch-list/get-filters.md"
    },
    {
      "name": "autocomplete_filter_values",
      "title": "Autocomplete filter values",
      "category": "Signal Agents",
      "description": "Autocompletes allowed values for a Signal Agent filter (job titles, industries, locations, company sizes, and more).",
      "method": "GET",
      "path": "/watchlist/filter-values",
      "path_params": [],
      "query_params": [
        {
          "name": "filterId",
          "type": "string",
          "required": true,
          "description": "Filter to resolve values for"
        },
        {
          "name": "query",
          "type": "string",
          "required": false,
          "description": "Search text (required for autocomplete filters). 1-100 characters."
        }
      ],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/watch-list/get-filter-values.md"
    },
    {
      "name": "list_deliverability_alerts",
      "title": "List Deliverability Alerts",
      "category": "Deliverability alerts",
      "description": "Lists all deliverability alert configurations for your team.",
      "method": "GET",
      "path": "/deliverability/alerts",
      "path_params": [],
      "query_params": [],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/deliverability-alerts/list-alerts.md"
    },
    {
      "name": "create_deliverability_alert",
      "title": "Create Deliverability Alert",
      "category": "Deliverability alerts",
      "description": "Creates a new deliverability alert that monitors a warm-up or outreach metric and notifies you through the configured channels when the threshold is breached.",
      "method": "POST",
      "path": "/deliverability/alerts",
      "path_params": [],
      "query_params": [],
      "body_content_type": "application/json",
      "body_required": true,
      "body_properties": [
        {
          "name": "widget",
          "type": "string",
          "required": true,
          "description": ""
        },
        {
          "name": "metric",
          "type": "string",
          "required": true,
          "description": ""
        },
        {
          "name": "severity",
          "type": "string",
          "required": true,
          "description": ""
        },
        {
          "name": "scope",
          "type": "string",
          "required": true,
          "description": ""
        },
        {
          "name": "scopeEntities",
          "type": "array",
          "required": false,
          "description": "Required when `scope` is `mailbox` or `domain` and you want to target specific entities. Mailbox entries use the format `userId|email|mailboxId`. Domain entries are bare domains (e.g. `acme.com`)."
        },
        {
          "name": "threshold",
          "type": "number",
          "required": true,
          "description": ""
        },
        {
          "name": "comparisonOperator",
          "type": "string",
          "required": true,
          "description": ""
        },
        {
          "name": "periodDays",
          "type": "integer",
          "required": true,
          "description": ""
        },
        {
          "name": "periodMode",
          "type": "string",
          "required": true,
          "description": ""
        },
        {
          "name": "channelConfig",
          "type": "string",
          "required": false,
          "description": ""
        },
        {
          "name": "recheckDelayHours",
          "type": "integer",
          "required": false,
          "description": "Cool-down between re-evaluations after the alert triggers, in hours. Defaults to 12."
        }
      ],
      "source": "https://developer.lemlist.com/api-reference/endpoints/deliverability-alerts/create-alert.md"
    },
    {
      "name": "get_deliverability_alert",
      "title": "Get Deliverability Alert",
      "category": "Deliverability alerts",
      "description": "Retrieves a single deliverability alert configuration by its ID.",
      "method": "GET",
      "path": "/deliverability/alerts/{alertId}",
      "path_params": [
        "alertId"
      ],
      "query_params": [],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/deliverability-alerts/get-alert.md"
    },
    {
      "name": "update_deliverability_alert",
      "title": "Update Deliverability Alert",
      "category": "Deliverability alerts",
      "description": "Updates a deliverability alert's threshold, evaluation window, notification channels, scope filter, or enabled state.",
      "method": "PATCH",
      "path": "/deliverability/alerts/{alertId}",
      "path_params": [
        "alertId"
      ],
      "query_params": [],
      "body_content_type": "application/json",
      "body_required": true,
      "body_properties": [
        {
          "name": "threshold",
          "type": "number",
          "required": false,
          "description": ""
        },
        {
          "name": "comparisonOperator",
          "type": "string",
          "required": false,
          "description": ""
        },
        {
          "name": "periodDays",
          "type": "integer",
          "required": false,
          "description": ""
        },
        {
          "name": "periodMode",
          "type": "string",
          "required": false,
          "description": ""
        },
        {
          "name": "channelConfig",
          "type": "string",
          "required": false,
          "description": ""
        },
        {
          "name": "scopeEntities",
          "type": "array",
          "required": false,
          "description": "Same format as on creation. Only meaningful when the alert's `scope` is `mailbox` or `domain`."
        },
        {
          "name": "enabled",
          "type": "boolean",
          "required": false,
          "description": "Pause or resume evaluation of this alert."
        }
      ],
      "source": "https://developer.lemlist.com/api-reference/endpoints/deliverability-alerts/update-alert.md"
    },
    {
      "name": "delete_deliverability_alert",
      "title": "Delete Deliverability Alert",
      "category": "Deliverability alerts",
      "description": "Permanently deletes a deliverability alert configuration. The historical alert occurrences this configuration produced are not removed.",
      "method": "DELETE",
      "path": "/deliverability/alerts/{alertId}",
      "path_params": [
        "alertId"
      ],
      "query_params": [],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/deliverability-alerts/delete-alert.md"
    },
    {
      "name": "list_fields",
      "title": "List Fields",
      "category": "Fields",
      "description": "Lists all available fields for contacts and companies.",
      "method": "GET",
      "path": "/fields",
      "path_params": [],
      "query_params": [
        {
          "name": "entity",
          "type": "string",
          "required": false,
          "description": "Filter by entity type"
        },
        {
          "name": "source",
          "type": "string",
          "required": false,
          "description": "Filter by field source"
        }
      ],
      "body_content_type": "",
      "body_required": false,
      "body_properties": [],
      "source": "https://developer.lemlist.com/api-reference/endpoints/fields/list-fields.md"
    }
  ]
}
''')
OPERATIONS: dict[str, dict[str, Any]] = {op["name"]: op for op in _CATALOG["operations"]}
_PATH_PARAMETER = re.compile(r"\{([^{}]+)\}")


class LemlistApiKeyCredential(BaseModel):
    credential_type: Literal["lemlist_api_key"] = Field(
        "lemlist_api_key", json_schema_extra={"ui:hidden": True}
    )
    api_key: str = Field(..., min_length=1, title="Lemlist API key", json_schema_extra={"ui:widget": "password"})

    model_config = ConfigDict(title="Lemlist API Key", json_schema_extra={
        "x-credential-url": "https://app.lemlist.com/settings/integrations",
        "x-credential-instructions": (
            "In Lemlist, open Settings → Integrations and generate an API key. "
            "Lemlist's REST API uses HTTP Basic authentication with an empty username and the API key as password."
        ),
    })


def _field_type(kind: str) -> type:
    if kind == "boolean":
        return bool
    if kind == "integer":
        return int
    if kind == "number":
        return float
    return str


def _operation_model(spec: dict[str, Any]) -> type[BaseModel]:
    name = spec["name"]
    fields: dict[str, Any] = {
        "operation": (Literal[name], Field(name, title=spec["title"], json_schema_extra={
            "const": name, "ui:hidden": True, "x-category": spec["category"],
            "x-display-name": spec["title"], "x-is-trigger": False,
        })),
    }
    for param in spec["path_params"]:
        fields[f"path_{param}"] = (str, Field(..., title=param, description=f"Path parameter {param}"))
    for param in spec["query_params"]:
        kind = param["type"]
        field_type = _field_type(kind)
        if kind in {"array", "object"}:
            description = (param["description"] + " Enter JSON.").strip()
        else:
            description = param["description"]
        required = param["required"]
        fields[f"query_{param['name']}"] = (
            field_type if required else Optional[field_type],
            Field(... if required else None, title=param["name"], description=description),
        )
    for prop in spec["body_properties"]:
        kind = prop["type"]
        field_type = _field_type(kind)
        description = prop["description"]
        if kind in {"array", "object"}:
            description = (description + " Enter JSON.").strip()
        required = prop["required"]
        fields[f"body_{prop['name']}"] = (
            field_type if required else Optional[field_type],
            Field(... if required else None, title=prop["name"], description=description),
        )
    fields["query_json"] = (Optional[str], Field(None, title="Additional query (JSON)",
        description="Optional query parameters as a JSON object", json_schema_extra={"ui:widget": "textarea"}))
    if spec["body_content_type"] == "multipart/form-data":
        fields["file_base64"] = (str, Field(..., title="Audio file (base64)",
            description="Base64-encoded audio bytes, without a data URL prefix", json_schema_extra={"ui:widget": "textarea"}))
        fields["file_name"] = (str, Field("audio.mp3", title="File name"))
        fields["file_content_type"] = (str, Field("audio/mpeg", title="Content type"))
    elif spec["method"] in {"POST", "PUT", "PATCH", "DELETE"}:
        fields["body_json"] = (Optional[str], Field(None, title="Additional body (JSON)",
            description="Optional full JSON request body or extra fields", json_schema_extra={"ui:widget": "textarea"}))
    return create_model(
        "Lemlist" + "".join(part.title() for part in name.split("_")) + "Config",
        __doc__=f"{spec['description']} ({spec['method']} {spec['path']}).",
        **fields,
    )


_OPERATION_MODELS = [_operation_model(spec) for spec in OPERATIONS.values()]
LemlistConfig = Annotated[Union[tuple(_OPERATION_MODELS)], Discriminator("operation")]


class LemlistNodeConfig(NodeConfig[LemlistConfig, LemlistApiKeyCredential]):
    pass


def _json_value(raw: str, *, label: str) -> Any:
    try:
        return json.loads(raw)
    except ValueError as exc:
        raise ValueError(f"{label} must be valid JSON") from exc


def _request_parts(op: BaseModel, spec: dict[str, Any]) -> tuple[str, dict[str, Any], Any]:
    path = spec["path"]
    for param in spec["path_params"]:
        value = str(getattr(op, f"path_{param}")).strip()
        if not value:
            raise ValueError(f"{param} is required")
        path = path.replace("{" + param + "}", quote(value, safe=""))
    if _PATH_PARAMETER.search(path):
        raise ValueError("A Lemlist path parameter is missing")

    query: dict[str, Any] = {}
    raw_query = getattr(op, "query_json", None)
    if raw_query:
        extra = _json_value(raw_query, label="Additional query")
        if not isinstance(extra, dict) or any(isinstance(v, dict) for v in extra.values()):
            raise ValueError("Additional query must be a flat JSON object")
        query.update(extra)
    for param in spec["query_params"]:
        value = getattr(op, f"query_{param['name']}")
        if value is not None:
            if param["type"] in {"array", "object"}:
                value = _json_value(value, label=param["name"])
            query[param["name"]] = value

    body: Any = None
    raw_body = getattr(op, "body_json", None)
    if raw_body:
        body = _json_value(raw_body, label="Request body")
    explicit = {}
    for prop in spec["body_properties"]:
        value = getattr(op, f"body_{prop['name']}")
        if value is not None:
            if prop["type"] in {"array", "object"}:
                value = _json_value(value, label=prop["name"])
            explicit[prop["name"]] = value
    if explicit:
        if body is None:
            body = {}
        if not isinstance(body, dict):
            raise ValueError("Request body must be a JSON object when individual fields are set")
        body.update(explicit)
    if spec["body_required"] and body is None and spec["body_content_type"] == "application/json":
        raise ValueError("This Lemlist operation requires a JSON request body")
    return path, query, body


class LemlistNode(WorkflowNode):
    """All documented Lemlist API operations using the account API key."""

    integration_type = "automation-lemlist"

    edit_examples = [
        "Add a new lead to a Lemlist outreach campaign",
        "Create a campaign and add contacts from a form",
        "Review campaign statistics and activity in a daily report",
    ]
    connection_evidence = ConnectionEvidence(operation="get_team", noun="team", label_keys=("name", "_id"))

    @classmethod
    def get_config_model(cls):
        return LemlistNodeConfig

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(self.config, LemlistNodeConfig):
            raise ValueError("Valid Lemlist configuration is required")
        op = self.config.config
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a Lemlist API key")
        spec = OPERATIONS[op.operation]
        path, query, body = _request_parts(op, spec)
        request_kwargs: dict[str, Any] = {
            "params": query or None,
            "headers": {"Accept": "application/json"},
            "auth": httpx.BasicAuth("", credential.api_key),
        }
        if spec["body_content_type"] == "multipart/form-data":
            try:
                raw = base64.b64decode(op.file_base64, validate=True)
            except (ValueError, binascii.Error) as exc:
                raise ValueError("Audio file must be valid base64") from exc
            if not raw:
                raise ValueError("Audio file is empty")
            request_kwargs["files"] = {"file": (op.file_name, raw, op.file_content_type)}
        elif body is not None:
            request_kwargs["json"] = body
        started = time.monotonic()
        try:
            async with guarded_async_client(timeout=45.0) as client:
                response = await client.request(spec["method"], API_BASE + path, **request_kwargs)
            elapsed = round((time.monotonic() - started) * 1000, 2)
            content_type = response.headers.get("content-type", "")
            if response.content and "json" in content_type:
                payload: Any = response.json()
            elif response.content:
                payload = {"content_type": content_type, "body": response.text[:1_000_000],
                           "truncated": len(response.text) > 1_000_000}
            else:
                payload = {"success": True}
            if response.is_error:
                result = {"status": "error", "action": op.operation, "error": payload,
                          "status_code": response.status_code, "timing_ms": {"api_request": elapsed}}
                if response.status_code == 429 and response.headers.get("retry-after"):
                    result["retry_after"] = response.headers["retry-after"]
                return result
            return {"status": "success", "action": op.operation, "data": payload,
                    "status_code": response.status_code, "timing_ms": {"api_request": elapsed}}
        except httpx.TimeoutException:
            return {"status": "error", "action": op.operation, "error": "Lemlist request timed out",
                    "status_code": 408, "timing_ms": {"api_request": round((time.monotonic() - started) * 1000, 2)}}
