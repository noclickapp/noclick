"""Mailchimp operation → OAuth scope requirements.

**Mailchimp's Marketing API has no granular OAuth scopes.** Its OAuth 2 flow
takes no ``scope`` parameter — the authorize request is client_id +
redirect_uri + state only — and the resulting token simply inherits the
authorizing user's account role, exactly like an account API key. There is no
per-endpoint permission to map, so every Marketing operation below declares an
empty requirement: authenticated is sufficient, and no operation can fail with
a scope error. The ``marketing:read`` / ``marketing:write`` strings sitting in
``x-oauth-scopes`` are ours, not Mailchimp's; they are never transmitted and
are left untouched here because live credentials carry them in metadata.

What Mailchimp does have is a **credential split**, and that is the failure this
table encodes. The 95 Transactional (Mandrill) operations talk to
``mandrillapp.com``, not the Marketing API, and ``_make_mandrill_request``
rejects anything but a ``mailchimp_mandrill`` credential — so a node connected
with OAuth can never run them, whatever it was granted. They sit in their own
tier with ``credential_types`` naming the credential that can satisfy them,
which keeps them out of the connect-time request (there is nothing to request)
and states the requirement in one place.
"""

from __future__ import annotations

from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement

#: Transactional operations are a different API behind a different key.
MANDRILL_TIER = "mandrill_transactional"

_MANDRILL_NOTE = (
    "Mandrill (Transactional) operations need a Mandrill API key. Connect a "
    "Mandrill credential — a Mailchimp OAuth or Marketing API key credential "
    "cannot reach mandrillapp.com."
)

#: Marketing API: authenticated is sufficient, but the credential must be one
#: that can sign a Marketing API request.
_MARKETING = ScopeRequirement(
    credential_types=("mailchimp_oauth", "mailchimp_api_key")
)

_MANDRILL = ScopeRequirement(
    tier=MANDRILL_TIER,
    credential_types=("mailchimp_mandrill",),
    note=_MANDRILL_NOTE,
)


#: Marketing API v3.0 operations, grouped by the operation picker's category.
MARKETING_OPERATIONS: tuple[str, ...] = (
    # Abuse Report
    "fetch_abuse_report",
    "list_abuse_reports",
    # Account
    "create_account_export",
    "disconnect_authorized_app",
    "fetch_account_export",
    "fetch_account_info",
    "fetch_activity_feed",
    "fetch_api_root_info",
    "fetch_authorized_app",
    "fetch_growth_history_for_month",
    "list_account_exports",
    "list_authorized_apps",
    "list_growth_history",
    "ping_api_connection",
    # Audience
    "create_audience",
    "delete_audience",
    "fetch_audience",
    "list_audiences",
    "update_audience_settings",
    # Automation
    "add_member_to_automation_queue",
    "archive_automation_workflow",
    "fetch_automation_email",
    "fetch_automation_queue_member",
    "fetch_automation_removed_member",
    "fetch_automation_workflow",
    "list_automation_emails",
    "list_automation_queue_members",
    "list_automation_removed_members",
    "list_automation_workflows",
    "pause_automation_email",
    "pause_automation_workflow",
    "remove_member_from_automation",
    "start_automation_email",
    "start_automation_workflow",
    # Batch
    "cancel_batch_request",
    "fetch_batch_status",
    "list_batch_operations",
    "start_batch_operation",
    # Campaign
    "add_campaign_feedback",
    "cancel_campaign_send",
    "create_campaign",
    "create_campaign_folder",
    "create_campaign_resend",
    "delete_campaign",
    "delete_campaign_feedback",
    "delete_campaign_folder",
    "duplicate_campaign",
    "fetch_campaign",
    "fetch_campaign_abuse_report",
    "fetch_campaign_advice",
    "fetch_campaign_checklist",
    "fetch_campaign_click_details",
    "fetch_campaign_click_details_for_member",
    "fetch_campaign_content",
    "fetch_campaign_domain_performance",
    "fetch_campaign_eepurl_activity",
    "fetch_campaign_email_activity",
    "fetch_campaign_feedback",
    "fetch_campaign_folder",
    "fetch_campaign_opens",
    "fetch_campaign_recipient_info",
    "fetch_campaign_report",
    "fetch_campaign_subreports",
    "fetch_campaign_top_locations",
    "fetch_campaign_unsubscribed_member",
    "fetch_link_click_details",
    "list_campaign_abuse_reports",
    "list_campaign_feedback",
    "list_campaign_folders",
    "list_campaign_recipients",
    "list_campaign_reports",
    "list_campaign_unsubscribes",
    "list_campaigns",
    "list_members_who_clicked_link",
    "pause_rss_campaign",
    "resume_rss_campaign",
    "schedule_campaign_for_delivery",
    "search_campaigns_by_name",
    "send_campaign_immediately",
    "send_campaign_test_email",
    "unschedule_campaign",
    "update_campaign_content",
    "update_campaign_folder",
    "update_campaign_settings",
    # Connected Site
    "create_connected_site",
    "delete_connected_site",
    "fetch_connected_site",
    "list_connected_sites",
    "update_connected_site",
    "verify_connected_site_script",
    # Conversation
    "delete_conversation_message",
    "fetch_conversation",
    "fetch_conversation_message",
    "list_conversation_messages",
    "list_conversations",
    "post_conversation_message",
    "update_conversation_message",
    # Domain
    "add_domain_for_verification",
    "delete_verified_domain",
    "fetch_verified_domain",
    "list_verified_domains",
    "update_verified_domain",
    "verify_domain_for_sending",
    # E-commerce Cart
    "create_cart_line_item",
    "create_ecommerce_cart",
    "delete_cart_line_item",
    "delete_ecommerce_cart",
    "fetch_cart_line_item",
    "fetch_ecommerce_cart",
    "list_cart_line_items",
    "list_ecommerce_carts",
    "update_cart_line_item",
    "update_ecommerce_cart",
    # E-commerce Customer
    "create_ecommerce_customer",
    "delete_ecommerce_customer",
    "fetch_ecommerce_customer",
    "list_ecommerce_customers",
    "update_ecommerce_customer",
    "upsert_ecommerce_customer",
    # E-commerce Order
    "create_ecommerce_order",
    "create_order_line_item",
    "delete_ecommerce_order",
    "delete_order_line_item",
    "fetch_ecommerce_order",
    "fetch_order_line_item",
    "list_all_ecommerce_orders",
    "list_ecommerce_orders",
    "list_order_line_items",
    "update_ecommerce_order",
    "update_order_line_item",
    # E-commerce Product
    "add_product_image",
    "create_ecommerce_product",
    "create_product_variant",
    "delete_ecommerce_product",
    "delete_product_image",
    "delete_product_variant",
    "fetch_ecommerce_product",
    "fetch_product_activity_report",
    "fetch_product_image",
    "fetch_product_variant",
    "list_ecommerce_products",
    "list_product_images",
    "list_product_variants",
    "update_ecommerce_product",
    "update_product_image",
    "update_product_variant",
    # E-commerce Store
    "create_ecommerce_store",
    "delete_ecommerce_store",
    "fetch_ecommerce_store",
    "list_ecommerce_stores",
    "update_ecommerce_store",
    # Facebook Ad
    "fetch_facebook_ad",
    "fetch_facebook_ad_ecommerce_activity",
    "fetch_facebook_ad_report",
    "list_facebook_ad_reports",
    "list_facebook_ads",
    # File
    "create_file_folder",
    "delete_file",
    "delete_file_folder",
    "fetch_file",
    "fetch_file_folder",
    "list_file_folders",
    "list_files",
    "list_files_in_folder",
    "update_file",
    "update_file_folder",
    "upload_file",
    # Interest
    "create_category_interest",
    "create_interest_category",
    "delete_category_interest",
    "delete_interest_category",
    "fetch_category_interest",
    "fetch_interest_category",
    "list_category_interests",
    "list_interest_categories",
    "update_category_interest",
    "update_interest_category",
    # Landing Page
    "create_landing_page",
    "delete_landing_page",
    "fetch_landing_page",
    "fetch_landing_page_content",
    "fetch_landing_page_report",
    "list_landing_page_reports",
    "list_landing_pages",
    "publish_landing_page",
    "unpublish_landing_page",
    "update_landing_page",
    "update_landing_page_html",
    # List
    "archive_list",
    "create_list",
    "fetch_list",
    "fetch_list_activity",
    "fetch_list_email_clients",
    "fetch_list_subscriber_locations",
    "list_all_lists",
    "update_list_settings",
    # List (x-category says 'Mandrill Tag' — Marketing endpoint)
    "search_list_tags",
    # Member
    "add_member_note",
    "archive_list_contact",
    "archive_list_member",
    "create_audience_contact",
    "create_list_member",
    "create_member_event",
    "delete_member_note",
    "fetch_audience_contact",
    "fetch_list_member",
    "fetch_member_activity",
    "fetch_member_campaign_opens",
    "fetch_member_goals",
    "fetch_member_note",
    "list_audience_contacts",
    "list_list_members",
    "list_member_activity_feed",
    "list_member_notes",
    "list_member_tags",
    "permanently_delete_contact_data",
    "permanently_delete_list_member",
    "search_list_members",
    "trigger_customer_journey_step",
    "update_audience_contact",
    "update_list_member",
    "update_member_note",
    "update_member_tags",
    "upsert_list_member",
    # Merge Field
    "create_merge_field",
    "delete_merge_field",
    "fetch_merge_field",
    "list_merge_fields",
    "update_merge_field",
    # Promo
    "create_promo_code",
    "create_promo_rule",
    "delete_promo_code",
    "delete_promo_rule",
    "fetch_promo_code",
    "fetch_promo_rule",
    "list_promo_codes",
    "list_promo_rules",
    "update_promo_code",
    "update_promo_rule",
    # Segment
    "add_member_to_segment",
    "create_list_segment",
    "delete_list_segment",
    "fetch_list_segment",
    "fetch_segment_member",
    "list_list_segments",
    "list_segment_members",
    "remove_member_from_segment",
    "update_list_segment",
    "update_segment_members_batch",
    # Signup Form
    "create_signup_form",
    "fetch_signup_forms",
    "list_signup_forms",
    "update_signup_form",
    # Survey
    "create_survey",
    "delete_survey",
    "fetch_survey",
    "fetch_survey_question",
    "fetch_survey_report",
    "fetch_survey_response",
    "list_survey_question_answers",
    "list_survey_questions",
    "list_survey_reports",
    "list_survey_responses",
    "list_surveys",
    "publish_survey",
    "send_survey_email",
    "unpublish_survey",
    "update_survey",
    # Template
    "create_email_template",
    "create_template_folder",
    "delete_email_template",
    "delete_template_folder",
    "fetch_email_template",
    "fetch_template_default_content",
    "fetch_template_folder",
    "list_email_templates",
    "list_template_folders",
    "update_email_template",
    "update_template_default_content",
    "update_template_folder",
    # Webhook
    "create_batch_webhook",
    "create_list_webhook",
    "delete_batch_webhook",
    "delete_list_webhook",
    "fetch_batch_webhook",
    "fetch_list_webhook",
    "list_batch_webhooks",
    "list_list_webhooks",
    "update_list_webhook",
)


#: Transactional API operations — Mandrill key only.
MANDRILL_OPERATIONS: tuple[str, ...] = (
    # Mandrill Allowlist
    "add_email_to_allowlist",
    "list_allowlisted_emails",
    "remove_email_from_allowlist",
    # Mandrill Denylist
    "add_email_to_denylist",
    "list_denylisted_emails",
    "remove_email_from_denylist",
    # Mandrill Export
    "export_activity_history",
    "export_allowlist",
    "export_denylist",
    "export_whitelist",
    "fetch_export_info",
    "list_exports",
    # Mandrill IP
    "cancel_ip_warmup",
    "create_ip_pool",
    "delete_ip_address",
    "delete_ip_pool",
    "fetch_ip_info",
    "fetch_ip_pool_info",
    "list_ip_addresses",
    "list_ip_pools",
    "move_ip_to_pool",
    "request_additional_ip",
    "set_ip_custom_dns",
    "start_ip_warmup",
    "test_ip_custom_dns",
    # Mandrill Inbound
    "add_inbound_domain",
    "add_mailbox_route",
    "delete_inbound_domain",
    "delete_mailbox_route",
    "list_inbound_domains",
    "list_mailbox_routes",
    "send_raw_mime_message",
    "update_mailbox_route",
    "verify_inbound_domain_settings",
    # Mandrill Message
    "cancel_scheduled_email",
    "fetch_message_content",
    "fetch_message_info",
    "list_scheduled_emails",
    "parse_mime_message",
    "reschedule_scheduled_email",
    "search_messages_by_date",
    "search_messages_by_hour",
    "send_message",
    "send_raw_mime_email",
    "send_sms_message",
    "send_templated_message",
    # Mandrill Metadata
    "create_metadata_field",
    "delete_metadata_field",
    "list_metadata_fields",
    "update_metadata_field",
    # Mandrill Sender
    "add_sender_domain",
    "fetch_sender_history",
    "fetch_sender_info",
    "list_account_senders",
    "list_sender_domains",
    "verify_sender_domain_for_sending",
    "verify_sender_domain_settings",
    # Mandrill Subaccount
    "create_subaccount",
    "delete_subaccount",
    "fetch_subaccount_info",
    "list_subaccounts",
    "pause_subaccount",
    "resume_subaccount",
    "update_subaccount",
    # Mandrill Tag
    "delete_tag",
    "fetch_all_tags_history",
    "fetch_tag_history",
    "fetch_tag_info",
    "list_tags",
    # Mandrill Template
    "create_mandrill_template",
    "delete_mandrill_template",
    "fetch_mandrill_template_history",
    "fetch_mandrill_template_info",
    "list_mandrill_templates",
    "publish_mandrill_template",
    "render_html_template",
    "update_mandrill_template",
    # Mandrill URL
    "add_tracking_domain",
    "fetch_url_history",
    "list_most_clicked_urls",
    "list_tracking_domains",
    "search_most_clicked_urls",
    "verify_tracking_domain_cname",
    # Mandrill User
    "fetch_user_info",
    "list_api_account_senders",
    "ping_mandrill_api",
    "ping_mandrill_api_v2",
    # Mandrill Webhook
    "create_mandrill_webhook",
    "delete_mandrill_webhook",
    "fetch_mandrill_webhook_info",
    "list_mandrill_webhooks",
    "update_mandrill_webhook",
    # Mandrill Whitelist
    "add_email_to_whitelist",
    "list_whitelisted_emails",
    "remove_email_from_whitelist",
)


_REQUIREMENTS: dict[str, ScopeRequirement] = {
    **{operation: _MARKETING for operation in MARKETING_OPERATIONS},
    **{operation: _MANDRILL for operation in MANDRILL_OPERATIONS},
}


MAILCHIMP_SCOPES = ScopeRegistry(
    provider="mailchimp",
    requirements=_REQUIREMENTS,
)
