"""Constant Contact V3 operation contracts from the official Swagger schema.

Source: https://api.cc.email/v3/swagger.yaml
Uses published path, method, parameter, and OAuth scope definitions.
The published schema omits A/B-test endpoints documented by the provider:
https://v3.developer.constantcontact.com/api_guide/email-campaigns-a-b-tests/ab-tests-get
https://v3.developer.constantcontact.com/api_guide/email-campaigns-a-b-tests/ab-tests-create
https://v3.developer.constantcontact.com/api_guide/email-campaigns-a-b-tests/ab-tests-delete
"""

from dataclasses import dataclass

@dataclass(frozen=True)
class Operation:
    method: str
    path: str
    label: str
    category: str
    scopes: tuple[str, ...]
    path_fields: tuple[str, ...]
    required_query_fields: tuple[str, ...]
    body_required: bool

OPERATIONS: dict[str, Operation] = {
    'get_user_privileges': Operation('GET', '/account/user/privileges', 'Get User Privileges', 'Account Services', (), (), (), False),
    'get_account_by_id': Operation('GET', '/account/summary', 'Get Account By ID', 'Account Services', ('account_read',), (), (), False),
    'put_customer_by_id': Operation('PUT', '/account/summary', 'Put Customer By ID', 'Account Services', ('account_update',), (), (), True),
    'get_physical_address': Operation('GET', '/account/summary/physical_address', 'Get Physical Address', 'Account Services', ('account_read',), (), (), False),
    'add_physical_address': Operation('POST', '/account/summary/physical_address', 'Add Physical Address', 'Account Services', ('account_update',), (), (), True),
    'put_physical_address': Operation('PUT', '/account/summary/physical_address', 'Put Physical Address', 'Account Services', ('account_update',), (), (), True),
    'get_company_logo': Operation('GET', '/account/summary/company_logo', 'Get Company Logo', 'Account Services', ('account_read',), (), (), False),
    'update_company_logo': Operation('PUT', '/account/summary/company_logo', 'Update Company Logo', 'Account Services', ('account_update',), (), (), True),
    'retrieve_email_addresses': Operation('GET', '/account/emails', 'Retrieve Email Addresses', 'Account Services', ('account_read',), (), (), False),
    'add_account_email_address': Operation('POST', '/account/emails', 'Add Account Email Address', 'Account Services', ('account_update',), (), (), True),
    'get_activity_status_collection': Operation('GET', '/activities', 'Get Activity Status Collection', 'Bulk Activities', ('contact_data',), (), (), False),
    'get_activity': Operation('GET', '/activities/{activity_id}', 'Get Activity', 'Bulk Activities', ('contact_data',), ('activity_id',), (), False),
    'post_contacts_export': Operation('POST', '/activities/contact_exports', 'Post Contacts Export', 'Bulk Activities', ('contact_data',), (), (), True),
    'get_contacts_export': Operation('GET', '/contact_exports/{file_export_id}', 'Get Contacts Export', 'Bulk Activities', ('contact_data',), ('file_export_id',), (), False),
    'post_contact_delete': Operation('POST', '/activities/contact_delete', 'Post Contact Delete', 'Bulk Activities', ('contact_data',), (), (), True),
    'bulk_import_contacts_json': Operation('POST', '/activities/contacts_json_import', 'Bulk Import Contacts JSON', 'Bulk Activities', ('contact_data',), (), (), True),
    'post_list_remove_contact': Operation('POST', '/activities/remove_list_memberships', 'Post List Remove Contact', 'Bulk Activities', ('contact_data',), (), (), True),
    'post_list_add_contact': Operation('POST', '/activities/add_list_memberships', 'Post List Add Contact', 'Bulk Activities', ('contact_data',), (), (), True),
    'post_list_delete': Operation('POST', '/activities/list_delete', 'Post List Delete', 'Bulk Activities', ('contact_data',), (), (), True),
    'post_tag_remove_contact': Operation('POST', '/activities/contacts_taggings_remove', 'Post Tag Remove Contact', 'Bulk Activities', ('contact_data',), (), (), True),
    'post_tag_add_contact': Operation('POST', '/activities/contacts_taggings_add', 'Post Tag Add Contact', 'Bulk Activities', ('contact_data',), (), (), True),
    'post_tag_delete': Operation('POST', '/activities/contacts_tags_delete', 'Post Tag Delete', 'Bulk Activities', ('contact_data',), (), (), True),
    'post_custom_field_delete': Operation('POST', '/activities/custom_fields_delete', 'Post Custom Field Delete', 'Bulk Activities', ('contact_data',), (), (), True),
    'get_account_segments': Operation('GET', '/segments', 'Get Account Segments', 'Segments', ('contact_data',), (), (), False),
    'create_segment': Operation('POST', '/segments', 'Create Segment', 'Segments', ('contact_data',), (), (), True),
    'get_segment_detail': Operation('GET', '/segments/{segment_id}', 'Get Segment Detail', 'Segments', ('contact_data',), ('segment_id',), (), False),
    'update_segment': Operation('PUT', '/segments/{segment_id}', 'Update Segment', 'Segments', ('contact_data',), ('segment_id',), (), True),
    'delete_segment': Operation('DELETE', '/segments/{segment_id}', 'Delete Segment', 'Segments', ('contact_data',), ('segment_id',), (), False),
    'update_segment_name': Operation('PATCH', '/segments/{segment_id}/name', 'Update Segment Name', 'Segments', ('contact_data',), ('segment_id',), (), True),
    'get_contact': Operation('GET', '/contacts/{contact_id}', 'Get Contact', 'Contacts', ('contact_data',), ('contact_id',), (), False),
    'put_contact': Operation('PUT', '/contacts/{contact_id}', 'Put Contact', 'Contacts', ('contact_data',), ('contact_id',), (), True),
    'delete_contact': Operation('DELETE', '/contacts/{contact_id}', 'Delete Contact', 'Contacts', ('contact_data',), ('contact_id',), (), False),
    'get_contacts': Operation('GET', '/contacts', 'List Contacts', 'Contacts', ('contact_data',), (), (), False),
    'create_contact': Operation('POST', '/contacts', 'Create Contact', 'Contacts', ('contact_data',), (), (), True),
    'create_or_update_contact': Operation('POST', '/contacts/sign_up_form', 'Create Or Update Contact', 'Contacts', ('contact_data',), (), (), True),
    'get_contact_id_xrefs': Operation('GET', '/contacts/contact_id_xrefs', 'Get Contact ID Xrefs', 'Contacts', ('contact_data',), (), ('sequence_ids',), False),
    'get_custom_field': Operation('GET', '/contact_custom_fields/{custom_field_id}', 'Get Custom Field', 'Contacts Custom Fields', ('contact_data',), ('custom_field_id',), (), False),
    'put_custom_field': Operation('PUT', '/contact_custom_fields/{custom_field_id}', 'Put Custom Field', 'Contacts Custom Fields', ('contact_data',), ('custom_field_id',), (), True),
    'delete_custom_field': Operation('DELETE', '/contact_custom_fields/{custom_field_id}', 'Delete Custom Field', 'Contacts Custom Fields', ('contact_data',), ('custom_field_id',), (), False),
    'get_custom_fields': Operation('GET', '/contact_custom_fields', 'Get Custom Fields', 'Contacts Custom Fields', ('contact_data',), (), (), False),
    'post_custom_fields': Operation('POST', '/contact_custom_fields', 'Post Custom Fields', 'Contacts Custom Fields', ('contact_data',), (), (), True),
    'get_list': Operation('GET', '/contact_lists/{list_id}', 'Get List', 'Contact Lists', ('contact_data',), ('list_id',), (), False),
    'put_list': Operation('PUT', '/contact_lists/{list_id}', 'Put List', 'Contact Lists', ('contact_data',), ('list_id',), (), True),
    'delete_list_activity': Operation('DELETE', '/contact_lists/{list_id}', 'Delete List Activity', 'Contact Lists', ('contact_data',), ('list_id',), (), False),
    'get_lists': Operation('GET', '/contact_lists', 'Get Lists', 'Contact Lists', ('contact_data',), (), (), False),
    'create_list': Operation('POST', '/contact_lists', 'Create List', 'Contact Lists', ('contact_data',), (), (), True),
    'get_list_id_xrefs': Operation('GET', '/contact_lists/list_id_xrefs', 'Get List ID Xrefs', 'Contact Lists', ('contact_data',), (), ('sequence_ids',), False),
    'get_sms_engagement_history': Operation('GET', '/contacts/sms_engagement_history/{contact_id}', 'Get SMS Engagement History', 'Contacts', ('contact_data',), ('contact_id',), (), False),
    'count_contact': Operation('GET', '/contacts/counts', 'Count Contact', 'Contacts', ('contact_data',), (), (), False),
    'resubscribe_contact': Operation('PUT', '/contacts/resubscribe/{contact_id}', 'Resubscribe Contact', 'Contacts', ('contact_data',), ('contact_id',), (), True),
    'get_tag': Operation('GET', '/contact_tags/{tag_id}', 'Get Tag', 'Contact Tags', ('contact_data',), ('tag_id',), (), False),
    'put_tag': Operation('PUT', '/contact_tags/{tag_id}', 'Put Tag', 'Contact Tags', ('contact_data',), ('tag_id',), (), True),
    'delete_tag': Operation('DELETE', '/contact_tags/{tag_id}', 'Delete Tag', 'Contact Tags', ('contact_data',), ('tag_id',), (), False),
    'get_tags': Operation('GET', '/contact_tags', 'Get Tags', 'Contact Tags', ('contact_data',), (), (), False),
    'post_tag': Operation('POST', '/contact_tags', 'Post Tag', 'Contact Tags', ('contact_data',), (), (), True),
    'retrieve_email_campaigns': Operation('GET', '/emails', 'Retrieve Email Campaigns', 'Email Campaigns', ('campaign_data',), (), (), False),
    'create_email_campaign': Operation('POST', '/emails', 'Create Email Campaign', 'Email Campaigns', ('campaign_data',), (), (), True),
    'retrieve_email_campaign': Operation('GET', '/emails/{campaign_id}', 'Retrieve Email Campaign', 'Email Campaigns', ('campaign_data',), ('campaign_id',), (), False),
    'remove_email_campaign': Operation('DELETE', '/emails/{campaign_id}', 'Remove Email Campaign', 'Email Campaigns', ('campaign_data',), ('campaign_id',), (), False),
    'rename_email_campaign': Operation('PATCH', '/emails/{campaign_id}', 'Rename Email Campaign', 'Email Campaigns', ('campaign_data',), ('campaign_id',), (), True),
    'retrieve_xref_mappings': Operation('GET', '/emails/campaign_id_xrefs', 'Retrieve Xref Mappings', 'Email Campaigns', ('campaign_data',), (), ('v2_email_campaign_ids',), False),
    'retrieve_email_campaign_activity': Operation('GET', '/emails/activities/{campaign_activity_id}', 'Retrieve Email Campaign Activity', 'Email Campaigns', ('campaign_data',), ('campaign_activity_id',), (), False),
    'update_email_campaign_activity': Operation('PUT', '/emails/activities/{campaign_activity_id}', 'Update Email Campaign Activity', 'Email Campaigns', ('campaign_data',), ('campaign_activity_id',), (), True),
    'retrieve_email_schedules': Operation('GET', '/emails/activities/{campaign_activity_id}/schedules', 'Retrieve Email Schedules', 'Email Scheduling', ('campaign_data',), ('campaign_activity_id',), (), False),
    'schedule_email_campaign_activity': Operation('POST', '/emails/activities/{campaign_activity_id}/schedules', 'Schedule Email Campaign Activity', 'Email Scheduling', ('campaign_data',), ('campaign_activity_id',), (), True),
    'unschedule_email_campaign_activity': Operation('DELETE', '/emails/activities/{campaign_activity_id}/schedules', 'Unschedule Email Campaign Activity', 'Email Scheduling', ('campaign_data',), ('campaign_activity_id',), (), False),
    'test_send_campaign_activity': Operation('POST', '/emails/activities/{campaign_activity_id}/tests', 'Test Send Campaign Activity', 'Email Scheduling', ('campaign_data',), ('campaign_activity_id',), (), True),
    'retrieve_email_campaign_activity_preview': Operation('GET', '/emails/activities/{campaign_activity_id}/previews', 'Retrieve Email Campaign Activity Preview', 'Email Scheduling', ('campaign_data',), ('campaign_activity_id',), (), False),
    'retrieve_email_send_history': Operation('GET', '/emails/activities/{campaign_activity_id}/send_history', 'Retrieve Email Send History', 'Email Scheduling', ('campaign_data',), ('campaign_activity_id',), (), False),
    'retrieve_resend_to_non_openers': Operation('GET', '/emails/activities/{campaign_activity_id}/non_opener_resends', 'Retrieve Resend To Non Openers', 'Email Campaigns', ('campaign_data',), ('campaign_activity_id',), (), False),
    'create_resend_to_non_openers': Operation('POST', '/emails/activities/{campaign_activity_id}/non_opener_resends', 'Create Resend To Non Openers', 'Email Campaigns', ('campaign_data',), ('campaign_activity_id',), (), True),
    'delete_resend_to_non_openers': Operation('DELETE', '/emails/activities/{campaign_activity_id}/non_opener_resends/{resend_request_id}', 'Delete Resend To Non Openers', 'Email Campaigns', ('campaign_data',), ('campaign_activity_id', 'resend_request_id'), (), False),
    'list_automations': Operation('GET', '/automations/workflows', 'List Automations', 'Automations', ('campaign_data',), (), (), False),
    'create_automation_campaign_using_post': Operation('POST', '/automations/workflows', 'Create Automation Campaign Using Post', 'Automations', ('campaign_data',), (), (), True),
    'retrieve_automation_campaign_using_get': Operation('GET', '/automations/workflows/{automation_flow_id}', 'Retrieve Automation Campaign Using Get', 'Automations', ('campaign_data',), ('automation_flow_id',), (), False),
    'update_automation_campaign_using_put': Operation('PUT', '/automations/workflows/{automation_flow_id}', 'Update Automation Campaign Using Put', 'Automations', ('campaign_data',), ('automation_flow_id',), (), True),
    'retrieve_email_campaign_ab_test': Operation('GET', '/emails/activities/{campaign_activity_id}/abtest', 'Retrieve Email Campaign AB Test', 'Email Campaigns AB Tests', ('campaign_data',), ('campaign_activity_id',), (), False),
    'create_email_campaign_ab_test': Operation('POST', '/emails/activities/{campaign_activity_id}/abtest', 'Create Email Campaign AB Test', 'Email Campaigns AB Tests', ('campaign_data',), ('campaign_activity_id',), (), True),
    'delete_email_campaign_ab_test': Operation('DELETE', '/emails/activities/{campaign_activity_id}/abtest', 'Delete Email Campaign AB Test', 'Email Campaigns AB Tests', ('campaign_data',), ('campaign_activity_id',), (), False),
    'get_contact_tracking': Operation('GET', '/reports/contact_reports/{contact_id}/activity_details', 'Get Contact Tracking', 'Contacts Reporting', ('contact_data',), ('contact_id',), (), False),
    'get_contact_open_click_rate': Operation('GET', '/reports/contact_reports/{contact_id}/open_and_click_rates', 'Get Contact Open Click Rate', 'Contacts Reporting', ('contact_data',), ('contact_id',), ('start', 'end'), False),
    'get_contact_tracking_count': Operation('GET', '/reports/contact_reports/{contact_id}/activity_summary', 'Get Contact Tracking Count', 'Contacts Reporting', ('contact_data',), ('contact_id',), ('start', 'end'), False),
    'get_campaign_activity_link_stats': Operation('GET', '/reports/email_reports/{campaign_activity_id}/links', 'Get Campaign Activity Link Stats', 'Email Reporting', ('campaign_data',), ('campaign_activity_id',), (), False),
    'get_sends': Operation('GET', '/reports/email_reports/{campaign_activity_id}/tracking/sends', 'Get Sends', 'Email Reporting', ('campaign_data',), ('campaign_activity_id',), (), False),
    'get_opens': Operation('GET', '/reports/email_reports/{campaign_activity_id}/tracking/opens', 'Get Opens', 'Email Reporting', ('campaign_data',), ('campaign_activity_id',), (), False),
    'get_unique_opens': Operation('GET', '/reports/email_reports/{campaign_activity_id}/tracking/unique_opens', 'Get Unique Opens', 'Email Reporting', ('campaign_data',), ('campaign_activity_id',), (), False),
    'get_did_not_opens': Operation('GET', '/reports/email_reports/{campaign_activity_id}/tracking/didnotopens', 'Get Did Not Opens', 'Email Reporting', ('campaign_data',), ('campaign_activity_id',), (), False),
    'get_clicks': Operation('GET', '/reports/email_reports/{campaign_activity_id}/tracking/clicks', 'Get Clicks', 'Email Reporting', ('campaign_data',), ('campaign_activity_id',), (), False),
    'get_forwards': Operation('GET', '/reports/email_reports/{campaign_activity_id}/tracking/forwards', 'Get Forwards', 'Email Reporting', ('campaign_data',), ('campaign_activity_id',), (), False),
    'get_optouts': Operation('GET', '/reports/email_reports/{campaign_activity_id}/tracking/optouts', 'Get Optouts', 'Email Reporting', ('campaign_data',), ('campaign_activity_id',), (), False),
    'get_bounces': Operation('GET', '/reports/email_reports/{campaign_activity_id}/tracking/bounces', 'Get Bounces', 'Email Reporting', ('campaign_data',), ('campaign_activity_id',), (), False),
    'get_campaign_performance_stats': Operation('GET', '/reports/email_reports/campaign_performance', 'Get Campaign Performance Stats', 'Contacts Reporting', ('contact_data',), (), (), False),
    'get_all_bulk_email_campaign_summaries': Operation('GET', '/reports/summary_reports/email_campaign_summaries', 'Get All Bulk Email Campaign Summaries', 'Email Reporting', ('campaign_data',), (), (), False),
    'get_email_summary': Operation('GET', '/reports/stats/email_campaigns/{campaign_ids}', 'Get Email Summary', 'Email Reporting', ('campaign_data',), ('campaign_ids',), (), False),
    'get_email_campaign_activity_summary': Operation('GET', '/reports/stats/email_campaign_activities/{campaign_activity_ids}', 'Get Email Campaign Activity Summary', 'Email Reporting', ('campaign_data',), ('campaign_activity_ids',), (), False),
}
