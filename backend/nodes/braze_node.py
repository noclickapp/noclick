"""Braze REST API workflow node with 150 documented operations."""

import json
import re
from typing import Annotated, Any, Literal, Optional, Union
from urllib.parse import quote, urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Discriminator, Field, field_validator, create_model

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence


from dataclasses import dataclass


@dataclass(frozen=True)
class Operation:
    label: str
    category: str
    method: str
    path: str
    body: bool
    permission: str
    query: tuple[tuple[str, bool, str, str], ...]
    docs_url: str


OPERATIONS: dict[str, Operation] = {
    'catalogs_delete_catalog': Operation('Delete catalog', 'Catalogs', 'DELETE', '/catalogs/{catalog_name}', True, 'catalogs.delete', (), 'https://www.braze.com/docs/api/endpoints/catalogs/catalog_management/synchronous/delete_catalog/'),
    'list_catalogs': Operation('List catalogs', 'Catalogs', 'GET', '/catalogs', False, 'catalogs.get', (), 'https://www.braze.com/docs/api/endpoints/catalogs/catalog_management/synchronous/get_list_catalogs/'),
    'catalogs_create_catalog': Operation('Create catalog', 'Catalogs', 'POST', '/catalogs', True, 'catalogs.create', (), 'https://www.braze.com/docs/api/endpoints/catalogs/catalog_management/synchronous/post_create_catalog/'),
    'catalogs_delete_multiple_catalog_items': Operation('Delete multiple catalog items', 'Catalogs', 'DELETE', '/catalogs/{catalog_name}/items', True, 'catalogs.delete_items', (), 'https://www.braze.com/docs/api/endpoints/catalogs/catalog_items/asynchronous/delete_catalog_items_bulk/'),
    'catalogs_edit_multiple_catalog_items': Operation('Edit multiple catalog items', 'Catalogs', 'PATCH', '/catalogs/{catalog_name}/items', True, 'catalogs.update_items', (), 'https://www.braze.com/docs/api/endpoints/catalogs/catalog_items/asynchronous/patch_catalog_items_bulk/'),
    'catalogs_create_multiple_catalog_items': Operation('Create multiple catalog items', 'Catalogs', 'POST', '/catalogs/{catalog_name}/items', True, 'catalogs.add_items', (), 'https://www.braze.com/docs/api/endpoints/catalogs/catalog_items/asynchronous/post_create_catalog_items_bulk/'),
    'catalogs_replace_catalog_items': Operation('Replace catalog items', 'Catalogs', 'PUT', '/catalogs/{catalog_name}/items', True, 'catalogs.replace_items', (), 'https://www.braze.com/docs/api/endpoints/catalogs/catalog_items/asynchronous/put_update_catalog_items/'),
    'catalogs_delete_a_catalog_item': Operation('Delete a catalog item', 'Catalogs', 'DELETE', '/catalogs/{catalog_name}/items/{item_id}', True, 'catalogs.delete_item', (), 'https://www.braze.com/docs/api/endpoints/catalogs/catalog_items/synchronous/delete_catalog_item/'),
    'catalogs_list_catalog_item_details': Operation('List catalog item details', 'Catalogs', 'GET', '/catalogs/{catalog_name}/items/{item_id}', False, 'catalogs.get_item', (), 'https://www.braze.com/docs/api/endpoints/catalogs/catalog_items/synchronous/get_catalog_item_details/'),
    'catalogs_list_multiple_catalog_item_details': Operation('List multiple catalog item details', 'Catalogs', 'GET', '/catalogs/{catalog_name}/items', False, 'catalogs.get_items', (), 'https://www.braze.com/docs/api/endpoints/catalogs/catalog_items/synchronous/get_catalog_items_details_bulk/'),
    'catalogs_edit_catalog_item': Operation('Edit catalog item', 'Catalogs', 'PATCH', '/catalogs/{catalog_name}/items/{item_id}', True, 'catalogs.update_item', (), 'https://www.braze.com/docs/api/endpoints/catalogs/catalog_items/synchronous/patch_catalog_item/'),
    'catalogs_create_catalog_item': Operation('Create catalog item', 'Catalogs', 'POST', '/catalogs/{catalog_name}/items/{item_id}', True, 'catalogs.create_item', (), 'https://www.braze.com/docs/api/endpoints/catalogs/catalog_items/synchronous/post_create_catalog_item/'),
    'catalogs_replace_catalog_item': Operation('Replace catalog item', 'Catalogs', 'PUT', '/catalogs/{catalog_name}/items/{item_id}', True, 'catalogs.replace_item', (), 'https://www.braze.com/docs/api/endpoints/catalogs/catalog_items/synchronous/put_update_catalog_item/'),
    'catalogs_delete_catalog_field': Operation('Delete catalog field', 'Catalogs', 'DELETE', '/catalogs/{catalog_name}/fields/{field_name}', True, 'catalogs.delete_fields', (), 'https://www.braze.com/docs/api/endpoints/catalogs/catalog_fields/asynchronous/delete_catalog_field/'),
    'catalogs_create_catalog_fields': Operation('Create catalog fields', 'Catalogs', 'POST', '/catalogs/{catalog_name}/fields', True, 'catalogs.create_fields', (), 'https://www.braze.com/docs/api/endpoints/catalogs/catalog_fields/asynchronous/post_create_catalog_fields/'),
    'catalogs_delete_catalog_selection': Operation('Delete catalog selection', 'Catalogs', 'DELETE', '/catalogs/{catalog_name}/selections/{selection_name}', True, 'catalogs.delete_selection', (), 'https://www.braze.com/docs/api/endpoints/catalogs/catalog_selections/asynchronous/delete_catalog_selection/'),
    'catalogs_create_catalog_selection': Operation('Create catalog selection', 'Catalogs', 'POST', '/catalogs/{catalog_name}/selections', True, 'catalogs.create_selection', (), 'https://www.braze.com/docs/api/endpoints/catalogs/catalog_selections/asynchronous/post_create_catalog_selections/'),
    'apps_update_push_credentials': Operation('Update push credentials', 'Apps', 'POST', '/apps/push_credential/update', True, 'apps.push_credential', (), 'https://www.braze.com/docs/api/endpoints/apps/post_update_push_credential/'),
    'list_integrations': Operation('List integrations', 'Cdi', 'GET', '/cdi/integrations', False, 'cdi.integration_list', (), 'https://www.braze.com/docs/api/endpoints/cdi/get_integration_list/'),
    'cdi_list_job_sync_status': Operation('List job sync status', 'Cdi', 'GET', '/cdi/integrations/{integration_id}/job_sync_status', False, 'cdi.integration_job_status', (), 'https://www.braze.com/docs/api/endpoints/cdi/get_job_sync_status/'),
    'cdi_trigger_a_sync': Operation('Trigger a sync', 'Cdi', 'POST', '/cdi/integrations/{integration_id}/sync', True, 'cdi.integration_sync', (), 'https://www.braze.com/docs/api/endpoints/cdi/post_job_sync/'),
    'email_query_hard_bounced_emails': Operation('Query hard bounced emails', 'Email', 'GET', '/email/hard_bounces', False, 'email.hard_bounces', (('start_date', False, 'String in YYYY-MM-DD format', '*One of start_date or email is required. This is the start date of the range to retrieve hard bounces and must be earlier than end_date . This is treated as midnight in UTC time by the API.'), ('end_date', True, 'String in YYYY-MM-DD format', 'End date of the range to retrieve hard bounces. This is treated as midnight in UTC time by the API.'), ('limit', False, 'Integer', 'Optional field to limit the number of results returned. Defaults to 100, maximum is 500.'), ('offset', False, 'Integer', 'Optional beginning point in the list to retrieve from.'), ('email', False, 'String', '*One of start_date or email is required. If provided, we’ll return whether or not the user has hard bounced. Check that the email strings are formatted properly.')), 'https://www.braze.com/docs/api/endpoints/email/get_list_hard_bounces/'),
    'email_query_list_of_unsubscribed_email_addresses': Operation('Query list of unsubscribed email addresses', 'Email', 'GET', '/email/unsubscribes', False, 'email.unsubscribe', (('start_date', False, 'String in YYYY-MM-DD format', 'Start date of the range to retrieve unsubscribes, must be earlier than end_date. This is treated as midnight in UTC time by the API.'), ('end_date', False, 'String in YYYY-MM-DD format', 'End date of the range to retrieve unsubscribes. This is treated as midnight in UTC time by the API.'), ('limit', False, 'Integer', 'Optional field to limit the number of results returned. Defaults to 100, maximum is 500.'), ('offset', False, 'Integer', 'Optional beginning point in the list to retrieve from.'), ('sort_direction', False, 'String', 'Pass in the value asc to sort unsubscribes from oldest to newest. Pass in desc to sort from newest to oldest. If sort_direction is not included, the default order is newest to oldest.'), ('email', False, 'String', 'If provided, we will return whether or not the user has unsubscribed.')), 'https://www.braze.com/docs/api/endpoints/email/get_query_unsubscribed_email_addresses/'),
    'email_change_email_subscription_status': Operation('Change email subscription status', 'Email', 'POST', '/email/status', True, 'email.status', (), 'https://www.braze.com/docs/api/endpoints/email/post_email_subscription_status/'),
    'email_remove_hard_bounced_emails': Operation('Remove hard bounced emails', 'Email', 'POST', '/email/bounce/remove', True, 'email.bounce.remove', (), 'https://www.braze.com/docs/api/endpoints/email/post_remove_hard_bounces/'),
    'email_remove_email_addresses_from_spam_list': Operation('Remove email addresses from spam list', 'Email', 'POST', '/email/spam/remove', True, 'email.spam.remove', (), 'https://www.braze.com/docs/api/endpoints/email/post_remove_spam/'),
    'email_blocklist_emails': Operation('Blocklist emails', 'Email', 'POST', '/email/blocklist', True, 'email.blacklist', (), 'https://www.braze.com/docs/api/endpoints/email/post_blocklist/'),
    'email_blacklist_emails': Operation('Blacklist emails', 'Email', 'POST', '/email/blacklist', True, 'email.blacklist', (), 'https://www.braze.com/docs/api/endpoints/email/post_blacklist/'),
    'export_export_campaign_analytics': Operation('Export campaign analytics', 'Export', 'GET', '/campaigns/data_series', False, 'campaigns.data_series', (('campaign_id', True, 'String', 'See campaign API identifier . The campaign_id for API campaigns can be found on the API Keys page and the Campaign Details page within your dashboard, or you can use the List campaigns endpoint .'), ('length', True, 'Integer', 'Maximum number of days before ending_at to include in the returned series. Must be between 1 and 100 (inclusive).'), ('ending_at', False, 'Datetime ( ISO-8601 string)', 'Date on which the data series should end. Defaults to time of the request.')), 'https://www.braze.com/docs/api/endpoints/export/campaigns/get_campaign_analytics/'),
    'export_export_campaign_details': Operation('Export campaign details', 'Export', 'GET', '/campaigns/details', False, 'campaigns.details', (('campaign_id', True, 'String', 'See campaign API identifier . The campaign_id for API campaigns can be found on the API Keys page and the Campaign Details page within your dashboard; or you can use the Export campaigns list endpoint .'), ('post_launch_draft_version', False, 'Boolean', 'For messages that have a post-launch draft, setting this to true shows any draft changes available. Defaults to false .'), ('include_has_translatable_content', False, 'Boolean', 'When set to true , the API response includes a has_translatable_content field for each message. Defaults to false .')), 'https://www.braze.com/docs/api/endpoints/export/campaigns/get_campaign_details/'),
    'list_campaigns': Operation('Export campaigns list', 'Export', 'GET', '/campaigns/list', False, 'campaigns.list', (('page', False, 'Integer', 'The page of campaigns to return, defaults to 0 (returns the first set of up to 100).'), ('include_archived', False, 'Boolean', 'Whether or not to include archived campaigns, defaults to false.'), ('sort_direction', False, 'String', '- Sort creation time from newest to oldest: pass in the value desc . - Sort creation time from oldest to newest: pass in the value asc . If sort_direction is not included, the default order is oldest to newest.'), ('last_edit.time[gt]', False, 'Time', 'Filters the results and only returns campaigns that were edited greater than the time provided till now. Format is yyyy-MM-DDTHH:mm:ss .')), 'https://www.braze.com/docs/api/endpoints/export/campaigns/get_campaigns/'),
    'export_export_send_analytics': Operation('Export send analytics', 'Export', 'GET', '/sends/data_series', False, 'sends.data_series', (('campaign_id', True, 'String', 'See campaign API identifier .'), ('send_id', True, 'String', 'See Send API identifier .'), ('length', True, 'Integer', 'Maximum number of days before ending_at to include in the returned series. Must be between 1 and 100 (inclusive).'), ('ending_at', False, 'Datetime ( ISO-8601 string)', 'Date on which the data series should end. Defaults to time of the request.')), 'https://www.braze.com/docs/api/endpoints/export/campaigns/get_send_analytics/'),
    'export_export_canvas_data_series_analytics': Operation('Export Canvas data series analytics', 'Export', 'GET', '/canvas/data_series', False, 'canvas.data_series', (('canvas_id', True, 'String', 'See Canvas API identifier .'), ('ending_at', True, 'Datetime ( ISO-8601 string)', 'Date on which the data export should end. Defaults to time of the request.'), ('starting_at', False, 'Datetime ( ISO-8601 string)', 'Date on which the data export should begin. * Either length or starting_at is required.'), ('length', False, 'String', 'Maximum number of days before ending_at to include in the returned series. Must be between 1 and 14 (inclusive). * Either length or starting_at is required.'), ('include_variant_breakdown', False, 'Boolean', 'Whether or not to include variant statistics (defaults to false ).'), ('include_step_breakdown', False, 'Boolean', 'Whether or not to include step statistics (defaults to false ).'), ('include_deleted_step_data', False, 'Boolean', 'Whether or not to include step statistics for deleted steps (defaults to false ).')), 'https://www.braze.com/docs/api/endpoints/export/canvas/get_canvas_analytics/'),
    'export_export_canvas_data_summary_analytics': Operation('Export Canvas data summary analytics', 'Export', 'GET', '/canvas/data_summary', False, 'canvas.data_summary', (('canvas_id', True, 'String', 'See Canvas API identifier .'), ('ending_at', True, 'Datetime ( ISO-8601 string)', 'End date for the data export. Defaults to the time of the request.'), ('starting_at', False, 'Datetime ( ISO-8601 string)', 'Start date for the data export. * Either length or starting_at is required.'), ('length', False, 'String', 'Maximum number of days before ending_at included in the returned series. Must be between 1 and 14 (inclusive). * Either length or starting_at is required.'), ('include_variant_breakdown', False, 'Boolean', 'Whether to include variant statistics (defaults to false ).'), ('include_step_breakdown', False, 'Boolean', 'Whether to include step statistics (defaults to false ).'), ('include_deleted_step_data', False, 'Boolean', 'Whether to include step statistics for deleted steps (defaults to false ).')), 'https://www.braze.com/docs/api/endpoints/export/canvas/get_canvas_analytics_summary/'),
    'export_export_canvas_details': Operation('Export Canvas details', 'Export', 'GET', '/canvas/details', False, 'canvas.details', (('canvas_id', True, 'String', 'See Canvas API Identifier'), ('post_launch_draft_version', False, 'Boolean', 'For Canvases that have a post-launch draft, setting this to true shows any draft changes available. Defaults to false .'), ('include_has_translatable_content', False, 'Boolean', 'When set to true , the API response includes a has_translatable_content field for each message. Defaults to false .')), 'https://www.braze.com/docs/api/endpoints/export/canvas/get_canvas_details/'),
    'list_canvases': Operation('Export Canvas list', 'Export', 'GET', '/canvas/list', False, 'canvas.list', (('page', False, 'Integer', 'The page of Canvases to return, defaults to 0 (returns the first set of up to 100)'), ('include_archived', False, 'Boolean', 'Whether or not to include archived Canvases, defaults to false .'), ('sort_direction', False, 'String', '- Sort creation time from newest to oldest: pass in the value desc . - Sort creation time from oldest to newest: pass in the value asc . If sort_direction is not included, the default order is oldest to newest.'), ('last_edit.time[gt]', False, 'Time', 'Filters the results and only returns Canvases that were edited greater than the time provided until now. Format is yyyy-MM-DDTHH:mm:ss .')), 'https://www.braze.com/docs/api/endpoints/export/canvas/get_canvases/'),
    'export_export_custom_events': Operation('Export custom events', 'Export', 'GET', '/events', False, 'events.get', (), 'https://www.braze.com/docs/api/endpoints/export/custom_events/get_custom_events_data/'),
    'export_export_custom_events_analytics': Operation('Export custom events analytics', 'Export', 'GET', '/events/data_series', False, 'events.data_series', (('event', True, 'String', 'The name of the custom event for which to return analytics.'), ('length', True, 'Integer', 'Maximum number of units (days or hours) before ending_at to include in the returned series. Must be between 1 and 100 (inclusive).'), ('unit', False, 'String', 'Unit of time between data points. Can be day or hour , defaults to day .'), ('ending_at', False, 'Datetime ( ISO-8601 string)', 'Date on which the data series should end. Defaults to time of the request.'), ('app_id', False, 'String', 'App API identifier retrieved from the API Keys page to limit analytics to a specific app.'), ('segment_id', False, 'String', 'See Segment API identifier . Segment ID indicating the analytics-enabled segment for which event analytics should be returned.')), 'https://www.braze.com/docs/api/endpoints/export/custom_events/get_custom_events_analytics/'),
    'export_export_custom_events_list': Operation('Export custom events list', 'Export', 'GET', '/events/list', False, 'events.list', (('page', False, 'Integer', 'The page of event names to return, defaults to 0 (returns the first set of up to 250).'),), 'https://www.braze.com/docs/api/endpoints/export/custom_events/get_custom_events/'),
    'export_export_daily_active_users_by_date': Operation('Export daily active users by date', 'Export', 'GET', '/kpi/dau/data_series', False, 'kpi.dau.data_series', (('length', True, 'Integer', 'Maximum number of days before ending_at to include in the returned series. Must be between 1 and 100 (inclusive).'), ('ending_at', False, 'Datetime ( ISO-8601 string)', 'Date on which the data series should end. Defaults to time of the request.'), ('app_id', False, 'String', 'App API identifier retrieved from the API Keys page. If excluded, results for all apps in workspace will be returned.')), 'https://www.braze.com/docs/api/endpoints/export/kpi/get_kpi_dau_date/'),
    'export_export_daily_new_users_by_date': Operation('Export daily new users by date', 'Export', 'GET', '/kpi/new_users/data_series', False, 'kpi.new_users.data_series', (('length', True, 'Integer', 'Maximum number of days before ending_at to include in the returned series. Must be between 1 and 100 (inclusive).'), ('ending_at', False, 'Datetime ( ISO-8601 string)', 'Date on which the data series should end. Defaults to time of the request.'), ('app_id', False, 'String', 'App API identifier retrieved from the API Keys page. If excluded, results for all apps in workspace will be returned.')), 'https://www.braze.com/docs/api/endpoints/export/kpi/get_kpi_daily_new_users_date/'),
    'export_export_kpis_for_daily_app_uninstalls_by_date': Operation('Export KPIs for daily app uninstalls by date', 'Export', 'GET', '/kpi/uninstalls/data_series', False, 'kpi.uninstalls.data_series', (('length', True, 'Integer', 'Maximum number of days before ending_at to include in the returned series. Must be between 1 and 100 (inclusive).'), ('ending_at', False, 'Datetime ( ISO-8601 string)', 'Date on which the data series should end. Defaults to time of the request.'), ('app_id', False, 'String', 'App API identifier retrieved from the API Keys page. If excluded, results for all apps in workspace will be returned.')), 'https://www.braze.com/docs/api/endpoints/export/kpi/get_kpi_uninstalls_date/'),
    'export_export_monthly_active_users_for_last_30_days': Operation('Export monthly active users for last 30 days', 'Export', 'GET', '/kpi/mau/data_series', False, 'kpi.mau.data_series', (('length', True, 'Integer', 'Maximum number of days before ending_at to include in the returned series. Must be between 1 and 100 (inclusive).'), ('ending_at', False, 'Datetime ( ISO-8601 string)', 'Date on which the data series should end. Defaults to time of the request.'), ('app_id', False, 'String', 'App API identifier retrieved from the API Keys page. If excluded, results for all apps in workspace will be returned.')), 'https://www.braze.com/docs/api/endpoints/export/kpi/get_kpi_mau_30_days/'),
    'export_export_product_ids': Operation('Export product IDs', 'Export', 'GET', '/purchases/product_list', False, 'purchases.product_list', (('page', False, 'String', 'The page of your product list that you want to view.'),), 'https://www.braze.com/docs/api/endpoints/export/purchases/get_list_product_id/'),
    'export_export_revenue_data_by_time': Operation('Export revenue data by time', 'Export', 'GET', '/purchases/revenue_series', False, 'purchases.revenue_series', (('ending_at', False, 'Datetime ( ISO-8601 string)', 'Date on which the data export should end. Defaults to time of the request.'), ('length', True, 'Integer', 'Maximum number of days before ending_at to include in the returned series. Must be between 1 and 100 (inclusive).'), ('unit', False, 'String', 'Unit of time between data points. Can be day or hour, defaults to day.'), ('app_id', False, 'String', 'App API identifier retrieved from the API Keys page. If excluded, results for all apps in a workspace will be returned.'), ('product', False, 'String', 'Name of product to filter response by. If excluded, results for all apps will be returned.')), 'https://www.braze.com/docs/api/endpoints/export/purchases/get_revenue_series/'),
    'export_export_number_of_purchases': Operation('Export number of purchases', 'Export', 'GET', '/purchases/quantity_series', False, 'purchases.quantity_series', (('ending_at', False, 'Datetime ( ISO-8601 string)', 'Date on which the data export should end. Defaults to time of the request.'), ('length', True, 'Integer', 'Maximum number of days before ending_at to include in the returned series. Must be between 1 and 100 (inclusive).'), ('unit', False, 'String', 'Unit of time between data points. Can be day or hour, defaults to day.'), ('app_id', False, 'String', 'App API identifier retrieved from the API Keys page. If excluded, results for all apps in a workspace will be returned.'), ('product', False, 'String', 'Name of product to filter response by. If excluded, results for all apps will be returned.')), 'https://www.braze.com/docs/api/endpoints/export/purchases/get_number_of_purchases/'),
    'export_export_segment_list': Operation('Export segment list', 'Export', 'GET', '/segments/list', False, 'segments.list', (('page', False, 'Integer', 'The page of segments to return, defaults to 0 (returns the first set of up to 100).'), ('sort_direction', False, 'String', '- Sort creation time from newest to oldest: pass in the value desc . - Sort creation time from oldest to newest: pass in the value asc . If sort_direction is not included, the default order is oldest to newest.')), 'https://www.braze.com/docs/api/endpoints/export/segments/get_segment/'),
    'export_export_segment_details': Operation('Export segment details', 'Export', 'GET', '/segments/details', False, 'segments.details', (('segment_id', True, 'String', 'See Segment API identifier . The segment_id for a given segment can be found on the API Keys page within your Braze account or you can use the Export segment list endpoint .'),), 'https://www.braze.com/docs/api/endpoints/export/segments/get_segment_details/'),
    'export_export_segment_analytics': Operation('Export segment analytics', 'Export', 'GET', '/segments/data_series', False, 'segments.data_series', (('segment_id', True, 'String', 'See Segment API identifier . The segment_id for a given segment can be found on the API Keys page within your Braze account or you can use the Export segment list endpoint .'), ('length', True, 'Integer', 'Maximum number of days before ending_at to include in the returned series. Must be between 1 and 100 (inclusive).'), ('ending_at', False, 'Datetime ( ISO-8601 string)', 'Date on which the data series should end. Defaults to time of the request.')), 'https://www.braze.com/docs/api/endpoints/export/segments/get_segment_analytics/'),
    'export_cancel_exports_by_segment': Operation('Cancel exports by segment', 'Export', 'POST', '/export/segment/cancel', True, 'segments.list', (), 'https://www.braze.com/docs/api/endpoints/export/segments/post_cancel_export/'),
    'export_export_app_session_by_time': Operation('Export app session by time', 'Export', 'GET', '/sessions/data_series', False, 'sessions.data_series', (('length', True, 'Integer', 'Maximum number of units (days or hours) before ending_at to include in the returned series. Must be between 1 and 100 (inclusive).'), ('unit', False, 'String', 'Unit of time between data points. Can be day or hour , defaults to day .'), ('ending_at', False, 'Datetime ( ISO-8601 string)', 'Date on which the data series should end. Defaults to time of the request.'), ('app_id', False, 'String', 'App API identifier retrieved from the API Keys page to limit analytics to a specific app.'), ('segment_id', False, 'String', 'See Segment API identifier . Segment ID indicating the analytics-enabled segment for which sessions should be returned.')), 'https://www.braze.com/docs/api/endpoints/export/sessions/get_sessions_analytics/'),
    'export_export_user_profile_by_identifier': Operation('Export user profile by identifier', 'Export', 'POST', '/users/export/ids', True, 'users.export.ids', (), 'https://www.braze.com/docs/api/endpoints/export/user_data/post_users_identifier/'),
    'export_export_user_profile_by_segment': Operation('Export user profile by segment', 'Export', 'POST', '/users/export/segment', True, 'users.export.segment', (), 'https://www.braze.com/docs/api/endpoints/export/user_data/post_users_segment/'),
    'export_export_user_profile_by_global_control_group': Operation('Export user profile by Global Control Group', 'Export', 'POST', '/users/export/global_control_group', True, 'users.export.global_control_group', (), 'https://www.braze.com/docs/api/endpoints/export/user_data/post_users_global_control_group/'),
    'export_export_custom_attributes': Operation('Export custom attributes', 'Export', 'GET', '/custom_attributes', False, 'custom_attributes.get', (), 'https://www.braze.com/docs/api/endpoints/export/custom_attributes/get_custom_attributes/'),
    'media_library_upload_an_asset_to_the_media_library': Operation('Upload an asset to the media library', 'Media Library', 'POST', '/media_library/create', True, 'media_library.create', (), 'https://www.braze.com/docs/api/endpoints/media_library/manage_assets/create/'),
    'media_library_replace_an_asset_in_the_media_library': Operation('Replace an asset in the media library', 'Media Library', 'PUT', '/media_library/replace_file', True, 'media_library.replace', (), 'https://www.braze.com/docs/api/endpoints/media_library/manage_assets/replace_file/'),
    'messaging_duplicate_campaigns_using_the_api': Operation('Duplicate campaigns using the API', 'Messaging', 'POST', '/campaigns/duplicate', True, 'campaigns.duplicate', (), 'https://www.braze.com/docs/api/endpoints/messaging/duplicate_messages/post_duplicate_campaigns/'),
    'messaging_duplicate_canvases_using_the_api': Operation('Duplicate Canvases using the API', 'Messaging', 'POST', '/canvas/duplicate', True, 'canvas.duplicate', (), 'https://www.braze.com/docs/api/endpoints/messaging/duplicate_messages/post_duplicate_canvases/'),
    'messaging_start_live_activity': Operation('Start Live Activity', 'Messaging', 'POST', '/messages/live_activity/start', True, 'messages.live_activity.start', (), 'https://www.braze.com/docs/api/endpoints/messaging/live_activity/start/'),
    'messaging_update_live_activity': Operation('Update Live Activity', 'Messaging', 'POST', '/messages/live_activity/update', True, 'messages.live_activity.update', (), 'https://www.braze.com/docs/api/endpoints/messaging/live_activity/update/'),
    'messaging_list_upcoming_scheduled_campaigns_and_canvases': Operation('List upcoming scheduled campaigns and Canvases', 'Messaging', 'GET', '/messages/scheduled_broadcasts', False, 'messages.schedule_broadcasts', (('end_time', True, 'String in ISO-8601 format', 'End date of the range to retrieve upcoming scheduled campaigns and Canvases. This is treated as midnight in UTC time by the API.'),), 'https://www.braze.com/docs/api/endpoints/messaging/schedule_messages/get_messages_scheduled/'),
    'messaging_create_scheduled_messages': Operation('Create scheduled messages', 'Messaging', 'POST', '/messages/schedule/create', True, 'messages.schedule.create', (), 'https://www.braze.com/docs/api/endpoints/messaging/schedule_messages/post_schedule_messages/'),
    'messaging_delete_scheduled_api_triggered_campaigns': Operation('Delete scheduled API-triggered campaigns', 'Messaging', 'POST', '/campaigns/trigger/schedule/delete', True, 'campaigns.trigger.schedule.delete', (), 'https://www.braze.com/docs/api/endpoints/messaging/schedule_messages/post_delete_scheduled_triggered_messages/'),
    'messaging_delete_scheduled_api_triggered_canvases': Operation('Delete scheduled API-triggered Canvases', 'Messaging', 'POST', '/canvas/trigger/schedule/delete', True, 'canvas.trigger.schedule.delete', (), 'https://www.braze.com/docs/api/endpoints/messaging/schedule_messages/post_delete_scheduled_triggered_canvases/'),
    'messaging_delete_scheduled_messages': Operation('Delete scheduled messages', 'Messaging', 'POST', '/messages/schedule/delete', True, 'messages.schedule.delete', (), 'https://www.braze.com/docs/api/endpoints/messaging/schedule_messages/post_delete_scheduled_messages/'),
    'messaging_schedule_api_triggered_campaigns': Operation('Schedule API-triggered campaigns', 'Messaging', 'POST', '/campaigns/trigger/schedule/create', True, 'campaigns.trigger.schedule.create', (), 'https://www.braze.com/docs/api/endpoints/messaging/schedule_messages/post_schedule_triggered_campaigns/'),
    'messaging_schedule_api_triggered_canvases': Operation('Schedule API-triggered Canvases', 'Messaging', 'POST', '/canvas/trigger/schedule/create', True, 'canvas.trigger.schedule.create', (), 'https://www.braze.com/docs/api/endpoints/messaging/schedule_messages/post_schedule_triggered_canvases/'),
    'messaging_update_scheduled_api_triggered_campaigns': Operation('Update scheduled API-triggered campaigns', 'Messaging', 'POST', '/campaigns/trigger/schedule/update', True, 'campaigns.trigger.schedule.update', (), 'https://www.braze.com/docs/api/endpoints/messaging/schedule_messages/post_update_scheduled_triggered_campaigns/'),
    'messaging_update_scheduled_api_triggered_canvases': Operation('Update scheduled API-triggered Canvases', 'Messaging', 'POST', '/canvas/trigger/schedule/update', True, 'canvas.trigger.schedule.update', (), 'https://www.braze.com/docs/api/endpoints/messaging/schedule_messages/post_update_scheduled_triggered_canvases/'),
    'messaging_update_scheduled_messages': Operation('Update scheduled messages', 'Messaging', 'POST', '/messages/schedule/update', True, 'messages.schedule.update', (), 'https://www.braze.com/docs/api/endpoints/messaging/schedule_messages/post_update_scheduled_messages/'),
    'messaging_create_send_ids': Operation('Create send IDs', 'Messaging', 'POST', '/sends/id/create', True, 'sends.id.create', (), 'https://www.braze.com/docs/api/endpoints/messaging/send_messages/post_create_send_ids/'),
    'messaging_send_campaign_messages_using_api_triggered_delivery': Operation('Send campaign messages using API-triggered delivery', 'Messaging', 'POST', '/campaigns/trigger/send', True, 'campaigns.trigger.send', (), 'https://www.braze.com/docs/api/endpoints/messaging/send_messages/post_send_triggered_campaigns/'),
    'messaging_send_canvas_messages_using_api_triggered_delivery': Operation('Send Canvas messages using API-triggered delivery', 'Messaging', 'POST', '/canvas/trigger/send', True, 'canvas.trigger.send', (), 'https://www.braze.com/docs/api/endpoints/messaging/send_messages/post_send_triggered_canvases/'),
    'messaging_send_messages_immediately_using_the_api_only': Operation('Send messages immediately using the API only', 'Messaging', 'POST', '/messages/send', True, 'messages.send', (), 'https://www.braze.com/docs/api/endpoints/messaging/send_messages/post_send_messages/'),
    'messaging_send_transactional_emails_using_api_triggered_delivery': Operation('Send transactional emails using API-triggered delivery', 'Messaging', 'POST', '/transactional/v1/campaigns/{campaign_id}/send', True, 'transactional.send', (), 'https://www.braze.com/docs/api/endpoints/messaging/send_messages/post_send_transactional_message/'),
    'preference_center_generate_preference_center_url': Operation('Generate preference center URL', 'Preference Center', 'GET', '/preference_center/v1/{preferenceCenterExternalID}/url/{userID}', False, 'preference_center.user.get', (('preference_center_api_id', True, 'String', 'The ID for your preference center.'), ('external_id', True, 'String', 'The external ID for a user.')), 'https://www.braze.com/docs/api/endpoints/preference_center/get_create_url_preference_center/'),
    'preference_center_list_preference_centers': Operation('List preference centers', 'Preference Center', 'GET', '/preference_center/v1/list', False, 'preference_center.list', (), 'https://www.braze.com/docs/api/endpoints/preference_center/get_list_preference_center/'),
    'preference_center_view_details_for_preference_center': Operation('View details for preference center', 'Preference Center', 'GET', '/preference_center/v1/{preferenceCenterExternalID}', False, 'preference_center.get', (), 'https://www.braze.com/docs/api/endpoints/preference_center/get_view_details_preference_center/'),
    'preference_center_create_preference_center': Operation('Create preference center', 'Preference Center', 'POST', '/preference_center/v1', True, 'preference_center.update', (), 'https://www.braze.com/docs/api/endpoints/preference_center/post_create_preference_center/'),
    'preference_center_update_preference_center': Operation('Update preference center', 'Preference Center', 'PUT', '/preference_center/v1/{preferenceCenterExternalID}', True, 'preference_center.update', (), 'https://www.braze.com/docs/api/endpoints/preference_center/put_update_preference_center/'),
    'scim_remove_dashboard_user_account': Operation('Remove dashboard user account', 'Scim', 'DELETE', '/scim/v2/Users/{id}', True, '', (), 'https://www.braze.com/docs/api/endpoints/scim/delete_existing_dashboard_user/'),
    'scim_look_up_an_existing_dashboard_user_account_by_resource_id': Operation('Look up an existing dashboard user account by resource ID', 'Scim', 'GET', '/scim/v2/Users/{id}', False, '', (), 'https://www.braze.com/docs/api/endpoints/scim/get_see_user_account_information/'),
    'scim_create_new_dashboard_user_account': Operation('Create new dashboard user account', 'Scim', 'POST', '/scim/v2/Users', True, '', (), 'https://www.braze.com/docs/api/endpoints/scim/post_create_user_account/'),
    'scim_update_dashboard_user_account': Operation('Update dashboard user account', 'Scim', 'PUT', '/scim/v2/Users/{id}', True, '', (), 'https://www.braze.com/docs/api/endpoints/scim/put_update_existing_user_account/'),
    'sdk_authentication_create_sdk_authentication_key': Operation('Create SDK Authentication key', 'Sdk Authentication', 'POST', '/app_group/sdk_authentication/create', True, 'sdk_authentication.create', (), 'https://www.braze.com/docs/api/endpoints/sdk_authentication/post_create_sdk_authentication_key/'),
    'sdk_authentication_list_sdk_authentication_keys': Operation('List SDK Authentication keys', 'Sdk Authentication', 'GET', '/app_group/sdk_authentication/keys', False, 'sdk_authentication.keys', (('app_id', True, 'String', 'The app API identifier.'),), 'https://www.braze.com/docs/api/endpoints/sdk_authentication/get_sdk_authentication_keys/'),
    'sdk_authentication_set_primary_sdk_authentication_key': Operation('Set primary SDK Authentication key', 'Sdk Authentication', 'PUT', '/app_group/sdk_authentication/primary', True, 'sdk_authentication.primary', (), 'https://www.braze.com/docs/api/endpoints/sdk_authentication/put_primary_sdk_authentication_key/'),
    'sdk_authentication_delete_sdk_authentication_key': Operation('Delete SDK Authentication key', 'Sdk Authentication', 'DELETE', '/app_group/sdk_authentication/delete', True, 'sdk_authentication.delete', (), 'https://www.braze.com/docs/api/endpoints/sdk_authentication/delete_sdk_authentication_key/'),
    'sms_query_invalid_phone_numbers': Operation('Query invalid phone numbers', 'Sms', 'GET', '/sms/invalid_phone_numbers', False, 'sms.invalid_phone_numbers', (('start_date', False, 'String in YYYY-MM-DD format', 'Start date of the range to retrieve invalid phone numbers, must be earlier than end_date . This is treated as midnight in UTC time by the API.'), ('end_date', False, 'String in YYYY-MM-DD format', 'End date of the range to retrieve invalid phone numbers. This is treated as midnight in UTC time by the API. Results include invalid numbers detected through the end of this calendar day in UTC (inclusive).'), ('limit', False, 'Integer', 'Optional field to limit the number of results returned. Defaults to 100, maximum is 500.'), ('offset', False, 'Integer', 'Optional beginning point in the list to retrieve from.'), ('phone_numbers', False, 'Array of Strings in e.164 format', 'If provided, Braze returns the phone number if it has been found to be invalid.'), ('reason', False, 'String', 'Available values are provider_error (the provider indicates the phone cannot receive SMS), deactivated (the phone number has been deactivated), or invalid_format (the number failed formatting validation, such as a non-E.164 value). If omitted, all reasons are returned.')), 'https://www.braze.com/docs/api/endpoints/sms/get_query_invalid_numbers/'),
    'sms_remove_invalid_phone_numbers': Operation('Remove invalid phone numbers', 'Sms', 'POST', '/sms/invalid_phone_numbers/remove', True, 'sms.invalid_phone_numbers.remove', (), 'https://www.braze.com/docs/api/endpoints/sms/post_remove_invalid_numbers/'),
    'subscription_groups_list_users_subscription_groups': Operation('List user’s subscription groups', 'Subscription Groups', 'GET', '/subscription/user/status', False, 'subscription.groups.get', (('external_id', False, 'String', 'The external_id of the user (must include at least one and at most 50 external_ids ).'), ('email', False, 'String', 'The email address of the user, can be passed as an array of strings. Must include at least one email address (with a maximum of 50).'), ('phone', False, 'String in E.164 format', 'The phone number of the user. Must include at least one phone number (with a maximum of 50).'), ('limit', False, 'Integer', 'The limit on the maximum number of results returned. Default (and maximum) limit is 100.'), ('offset', False, 'Integer', 'Number of templates to skip before returning the rest of the templates that fit the search criteria.')), 'https://www.braze.com/docs/api/endpoints/subscription_groups/get_list_user_subscription_groups/'),
    'subscription_groups_list_users_subscription_group_status': Operation('List user’s subscription group status', 'Subscription Groups', 'GET', '/subscription/status/get', False, 'subscription.status.get', (('subscription_group_id', True, 'String', 'The id of your subscription group.'), ('external_id', False, 'String', 'The external_id of the user (must include at least one and at most 50 external_ids ). When both an external_id and email / phone are submitted, only the external_id (s) provided will be applied to the result query.'), ('email', False, 'String', 'The email address of the user. It can be passed as an array of strings with a maximum of 50. Submitting both an email address and phone number (with no external_id ) will result in an error.'), ('phone', False, 'String in E.164 format', 'The phone number of the user. If email is not included, you must include at least one phone number (with a maximum of 50). Submitting both an email address and phone number (with no external_id ) will result in an error.')), 'https://www.braze.com/docs/api/endpoints/subscription_groups/get_list_user_subscription_group_status/'),
    'subscription_groups_update_users_subscription_group_status': Operation('Update user’s subscription group status', 'Subscription Groups', 'POST', '/subscription/status/set', True, 'subscription.status.set', (), 'https://www.braze.com/docs/api/endpoints/subscription_groups/post_update_user_subscription_group_status/'),
    'subscription_groups_update_users_subscription_group_status_v2': Operation('Update user’s subscription group status (V2)', 'Subscription Groups', 'POST', '/v2/subscription/status/set', True, 'subscription.status.set', (), 'https://www.braze.com/docs/api/endpoints/subscription_groups/post_update_user_subscription_group_status_v2/'),
    'templates_list_available_content_blocks': Operation('List available Content Blocks', 'Templates', 'GET', '/content_blocks/list', False, 'content_blocks.list', (('modified_after', False, 'String in ISO-8601 format', 'Retrieve only Content Blocks updated at or after the given time.'), ('modified_before', False, 'String in ISO-8601 format', 'Retrieve only Content Blocks updated at or before the given time.'), ('limit', False, 'Positive Number', 'Maximum number of Content Blocks to retrieve. Default to 100 if not provided, with a maximum acceptable value of 1000.'), ('offset', False, 'Positive Number', 'Number of Content Blocks to skip before returning rest of the templates that fit the search criteria.')), 'https://www.braze.com/docs/api/endpoints/templates/content_blocks_templates/get_list_email_content_blocks/'),
    'templates_see_content_block_information': Operation('See Content Block information', 'Templates', 'GET', '/content_blocks/info', False, 'content_blocks.info', (('content_block_id', True, 'String', 'The Content Block identifier. You can find this by either listing Content Block information through an API call or going to the API Keys page, then scrolling to the bottom and searching for your Content Block API identifier.'), ('include_inclusion_data', False, 'Boolean', 'When set to true , the API returns back the Message Variation API identifier of campaigns and Canvases where this Content Block is included, to be used in subsequent calls.  The results exclude archived or deleted campaigns or Canvases.')), 'https://www.braze.com/docs/api/endpoints/templates/content_blocks_templates/get_see_email_content_blocks_information/'),
    'templates_create_content_block': Operation('Create Content Block', 'Templates', 'POST', '/content_blocks/create', True, 'content_blocks.create', (), 'https://www.braze.com/docs/api/endpoints/templates/content_blocks_templates/post_create_email_content_block/'),
    'templates_update_content_block': Operation('Update Content Block', 'Templates', 'POST', '/content_blocks/update', True, 'content_blocks.update', (), 'https://www.braze.com/docs/api/endpoints/templates/content_blocks_templates/post_update_content_block/'),
    'list_email_templates': Operation('List available email templates', 'Templates', 'GET', '/templates/email/list', False, 'templates.email.list', (('modified_after', False, 'String in ISO-8601 format', 'Retrieve only templates updated at or after the given time.'), ('modified_before', False, 'String in ISO-8601 format', 'Retrieve only templates updated at or before the given time.'), ('limit', False, 'Positive number', 'Maximum number of templates to retrieve. Default to 100 if not provided, with a maximum acceptable value of 1000.'), ('offset', False, 'Positive number', 'Number of templates to skip before returning rest of the templates that fit the search criteria.')), 'https://www.braze.com/docs/api/endpoints/templates/email_templates/get_list_email_templates/'),
    'templates_see_email_template_information': Operation('See email template information', 'Templates', 'GET', '/templates/email/info', False, 'templates.email.info', (('email_template_id', True, 'String', 'See email template API identifier .'),), 'https://www.braze.com/docs/api/endpoints/templates/email_templates/get_see_email_template_information/'),
    'templates_create_email_template': Operation('Create email template', 'Templates', 'POST', '/templates/email/create', True, 'templates.email.create', (), 'https://www.braze.com/docs/api/endpoints/templates/email_templates/post_create_email_template/'),
    'templates_update_existing_email_templates': Operation('Update existing email templates', 'Templates', 'POST', '/templates/email/update', True, 'templates.email.update', (), 'https://www.braze.com/docs/api/endpoints/templates/email_templates/post_update_email_template/'),
    'translations_view_all_translations_for_a_campaign': Operation('View all translations for a campaign', 'Translations', 'GET', '/campaigns/translations', False, 'campaigns.translations.get', (), 'https://www.braze.com/docs/api/endpoints/translations/campaigns/get_translation_campaign/'),
    'translations_update_translation_in_a_campaign': Operation('Update translation in a campaign', 'Translations', 'PUT', '/campaigns/translations', True, 'campaigns.translations.update', (), 'https://www.braze.com/docs/api/endpoints/translations/campaigns/put_update_translation_campaign/'),
    'translations_view_default_source_values_for_a_campaigns_translation_tags': Operation('View default source values for a campaign’s translation tags', 'Translations', 'GET', '/campaigns/translations/source', False, 'campaigns.translations.get', (), 'https://www.braze.com/docs/api/endpoints/translations/campaigns/get_source_campaign/'),
    'translations_view_default_source_values_for_a_content_blocks_translation_tags': Operation('View default source values for a Content Block’s translation tags', 'Translations', 'GET', '/content_blocks/translations/source', False, 'content_blocks.translations.get', (), 'https://www.braze.com/docs/api/endpoints/translations/content_blocks/get_source_content_block/'),
    'translations_view_all_translations_for_a_content_block': Operation('View all translations for a Content Block', 'Translations', 'GET', '/content_blocks/translations', False, 'content_blocks.translations.get', (), 'https://www.braze.com/docs/api/endpoints/translations/content_blocks/get_translation_content_block/'),
    'translations_update_translation_in_a_content_block': Operation('Update translation in a Content Block', 'Translations', 'PUT', '/content_blocks/translations', True, 'content_blocks.translations.update', (), 'https://www.braze.com/docs/api/endpoints/translations/content_blocks/put_update_translation_content_block/'),
    'translations_view_translation_for_a_canvas': Operation('View translation for a Canvas', 'Translations', 'GET', '/canvas/translations', False, 'canvas.translations.get', (), 'https://www.braze.com/docs/api/endpoints/translations/canvas/get_translation_canvas/'),
    'translations_update_translation_in_a_canvas': Operation('Update translation in a Canvas', 'Translations', 'PUT', '/canvas/translations', True, 'canvas.translations.update', (), 'https://www.braze.com/docs/api/endpoints/translations/canvas/put_update_translation_canvas/'),
    'translations_view_default_source_values_for_a_canvass_translation_tags': Operation('View default source values for a canvas’s translation tags', 'Translations', 'GET', '/canvas/translations/source', False, 'canvas.translations.get', (), 'https://www.braze.com/docs/api/endpoints/translations/canvas/get_source_canvas/'),
    'translations_view_the_source_translations_for_an_email_template': Operation('View the source translations for an email template', 'Translations', 'GET', '/templates/email/translations/source', False, 'templates.email.info', (), 'https://www.braze.com/docs/api/endpoints/translations/email_templates/get_view_source_template/'),
    'translations_view_a_specific_translation_and_locale_for_email_template_endpoint': Operation('View a specific translation and locale for email template endpoint', 'Translations', 'GET', '/templates/translations/email', False, 'templates.translations.get', (), 'https://www.braze.com/docs/api/endpoints/translations/email_templates/get_view_translation_locale_template/'),
    'translations_view_all_translations_and_locales_for_an_email_template': Operation('View all translations and locales for an email template', 'Translations', 'GET', '/templates/email/translations/', False, 'templates.translations.get', (), 'https://www.braze.com/docs/api/endpoints/translations/email_templates/get_view_translation_template/'),
    'translations_update_translations_for_an_email_template': Operation('Update translations for an email template', 'Translations', 'PUT', '/templates/email/translations/', True, 'templates.translations.update', (), 'https://www.braze.com/docs/api/endpoints/translations/email_templates/put_update_template/'),
    'translations_view_source_translations_for_a_webhook_template': Operation('View source translations for a webhook template', 'Translations', 'GET', '/templates/webhook/translations/source', False, 'templates.translations.get', (), 'https://www.braze.com/docs/api/endpoints/translations/webhook_templates/get_view_source_webhook_template/'),
    'translations_view_translations_for_a_webhook_template': Operation('View translations for a webhook template', 'Translations', 'GET', '/templates/webhook/translations', False, 'templates.translations.get', (), 'https://www.braze.com/docs/api/endpoints/translations/webhook_templates/get_view_translations_webhook_template/'),
    'translations_update_translations_for_a_webhook_template': Operation('Update translations for a webhook template', 'Translations', 'PUT', '/templates/webhook/translations', True, 'templates.translations.update', (), 'https://www.braze.com/docs/api/endpoints/translations/webhook_templates/put_update_webhook_template/'),
    'user_data_create_new_user_alias': Operation('Create new user alias', 'User Data', 'POST', '/users/alias/new', True, 'users.alias.new', (), 'https://www.braze.com/docs/api/endpoints/user_data/post_user_alias/'),
    'user_data_update_user_alias': Operation('Update user alias', 'User Data', 'POST', '/users/alias/update', True, 'users.alias.update', (), 'https://www.braze.com/docs/api/endpoints/user_data/post_users_alias_update/'),
    'user_data_identify_users': Operation('Identify users', 'User Data', 'POST', '/users/identify', True, 'users.identify', (), 'https://www.braze.com/docs/api/endpoints/user_data/post_user_identify/'),
    'track_users': Operation('Create and update users', 'User Data', 'POST', '/users/track', True, 'users.track', (), 'https://www.braze.com/docs/api/endpoints/user_data/post_user_track/'),
    'user_data_create_and_update_users_bulk': Operation('Create and update users (bulk)', 'User Data', 'POST', '/users/track/bulk', True, 'users.track.bulk', (), 'https://www.braze.com/docs/api/endpoints/user_data/post_user_track_bulk/'),
    'user_data_create_and_update_users_synchronous': Operation('Create and update users (synchronous)', 'User Data', 'POST', '/users/track/sync', True, 'users.track.sync', (), 'https://www.braze.com/docs/api/endpoints/user_data/post_user_track_synchronous/'),
    'user_data_look_up_request_processing_status': Operation('Look up request processing status', 'User Data', 'GET', '/users/track/status', False, 'users.track.status', (), 'https://www.braze.com/docs/api/endpoints/user_data/get_users_track_status/'),
    'user_data_delete_users': Operation('Delete users', 'User Data', 'POST', '/users/delete', True, 'users.delete', (), 'https://www.braze.com/docs/api/endpoints/user_data/post_user_delete/'),
    'user_data_merge_users': Operation('Merge users', 'User Data', 'POST', '/users/merge', True, 'users.merge', (), 'https://www.braze.com/docs/api/endpoints/user_data/post_users_merge/'),
    'user_data_rename_external_id': Operation('Rename external ID', 'User Data', 'POST', '/users/external_ids/rename', True, 'users.external_ids.rename', (), 'https://www.braze.com/docs/api/endpoints/user_data/external_id_migration/post_external_ids_rename/'),
    'user_data_remove_external_id': Operation('Remove external ID', 'User Data', 'POST', '/users/external_ids/remove', True, 'users.external_ids.remove', (), 'https://www.braze.com/docs/api/endpoints/user_data/external_id_migration/post_external_ids_remove/'),
    'data_objects_list_data_object_types': Operation('List data object types', 'Data Objects', 'GET', '/data_objects/types', False, '', (), 'https://www.braze.com/docs/api/endpoints/data_objects/types/get_list_data_object_types/'),
    'data_objects_get_data_object_type': Operation('Get data object type', 'Data Objects', 'GET', '/data_objects/types/{type_name}', False, '', (), 'https://www.braze.com/docs/api/endpoints/data_objects/types/get_data_object_type/'),
    'data_objects_list_user_relationship_types': Operation('List user relationship types', 'Data Objects', 'GET', '/data_objects/types/{type_name}/user_relationship_types', False, '', (), 'https://www.braze.com/docs/api/endpoints/data_objects/types/get_list_user_relationship_types/'),
    'data_objects_list_object_relationship_types': Operation('List object relationship types', 'Data Objects', 'GET', '/data_objects/types/{type_name}/object_relationship_types', False, '', (), 'https://www.braze.com/docs/api/endpoints/data_objects/types/get_list_object_relationship_types/'),
    'data_objects_list_data_objects': Operation('List data objects', 'Data Objects', 'GET', '/data_objects/objects/{type_name}', False, '', (), 'https://www.braze.com/docs/api/endpoints/data_objects/objects/get_list_data_objects/'),
    'data_objects_get_data_object': Operation('Get data object', 'Data Objects', 'GET', '/data_objects/objects/{type_name}/{object_id}', False, '', (), 'https://www.braze.com/docs/api/endpoints/data_objects/objects/get_data_object/'),
    'data_objects_create_data_object': Operation('Create data object', 'Data Objects', 'POST', '/data_objects/objects/{type_name}', True, '', (), 'https://www.braze.com/docs/api/endpoints/data_objects/objects/post_create_data_object/'),
    'data_objects_replace_data_object': Operation('Replace data object', 'Data Objects', 'PUT', '/data_objects/objects/{type_name}/{object_id}', True, '', (), 'https://www.braze.com/docs/api/endpoints/data_objects/objects/put_replace_data_object/'),
    'data_objects_update_data_object': Operation('Update data object', 'Data Objects', 'PATCH', '/data_objects/objects/{type_name}/{object_id}', True, '', (), 'https://www.braze.com/docs/api/endpoints/data_objects/objects/patch_update_data_object/'),
    'data_objects_delete_data_object': Operation('Delete data object', 'Data Objects', 'DELETE', '/data_objects/objects/{type_name}/{object_id}', True, '', (), 'https://www.braze.com/docs/api/endpoints/data_objects/objects/delete_data_object/'),
    'data_objects_list_object_relationships': Operation('List object relationships', 'Data Objects', 'GET', '/data_objects/objects/{type_name}/{object_id}/object_relationships', False, '', (), 'https://www.braze.com/docs/api/endpoints/data_objects/object_relationships/get_list_object_relationships/'),
    'data_objects_create_object_relationship': Operation('Create object relationship', 'Data Objects', 'POST', '/data_objects/objects/{type_name}/{object_id}/object_relationships', True, '', (), 'https://www.braze.com/docs/api/endpoints/data_objects/object_relationships/post_create_object_relationship/'),
    'data_objects_replace_object_relationship': Operation('Replace object relationship', 'Data Objects', 'PUT', '/data_objects/objects/{type_name}/{object_id}/object_relationships', True, '', (), 'https://www.braze.com/docs/api/endpoints/data_objects/object_relationships/put_replace_object_relationship/'),
    'data_objects_update_object_relationship': Operation('Update object relationship', 'Data Objects', 'PATCH', '/data_objects/objects/{type_name}/{object_id}/object_relationships', True, '', (), 'https://www.braze.com/docs/api/endpoints/data_objects/object_relationships/patch_update_object_relationship/'),
    'data_objects_delete_object_relationship': Operation('Delete object relationship', 'Data Objects', 'DELETE', '/data_objects/objects/{type_name}/{object_id}/object_relationships', True, '', (), 'https://www.braze.com/docs/api/endpoints/data_objects/object_relationships/delete_object_relationship/'),
    'data_objects_list_user_relationships': Operation('List user relationships', 'Data Objects', 'GET', '/data_objects/objects/{type_name}/{object_id}/user_relationships', False, '', (), 'https://www.braze.com/docs/api/endpoints/data_objects/user_relationships/get_list_user_relationships/'),
    'data_objects_create_user_relationship': Operation('Create user relationship', 'Data Objects', 'POST', '/data_objects/objects/{type_name}/{object_id}/users', True, '', (), 'https://www.braze.com/docs/api/endpoints/data_objects/user_relationships/post_create_user_relationship/'),
    'data_objects_replace_user_relationship': Operation('Replace user relationship', 'Data Objects', 'PUT', '/data_objects/objects/{type_name}/{object_id}/users', True, '', (), 'https://www.braze.com/docs/api/endpoints/data_objects/user_relationships/put_replace_user_relationship/'),
    'data_objects_update_user_relationship': Operation('Update user relationship', 'Data Objects', 'PATCH', '/data_objects/objects/{type_name}/{object_id}/users', True, '', (), 'https://www.braze.com/docs/api/endpoints/data_objects/user_relationships/patch_update_user_relationship/'),
    'data_objects_delete_user_relationship': Operation('Delete user relationship', 'Data Objects', 'DELETE', '/data_objects/objects/{type_name}/{object_id}/users', True, '', (), 'https://www.braze.com/docs/api/endpoints/data_objects/user_relationships/delete_user_relationship/'),
}


class BrazeApiKeyCredential(BaseModel):
    credential_type: Literal["braze_api_key"] = Field("braze_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="REST API Key", description="A Braze REST API key with permissions for the operations you use.", json_schema_extra={"ui:widget": "password"})
    rest_endpoint: str = Field(..., title="REST Endpoint", description="The REST endpoint shown beside your Braze API key, for example https://rest.iad-01.braze.com")
    model_config = ConfigDict(title="Braze REST API Key", json_schema_extra={
        "x-credential-url": "https://www.braze.com/docs/api/basics#creating-rest-api-keys",
    })

    @field_validator("rest_endpoint")
    @classmethod
    def validate_rest_endpoint(cls, value: str) -> str:
        value = value.rstrip("/")
        parsed = urlsplit(value)
        host = parsed.hostname or ""
        if (parsed.scheme != "https" or parsed.port is not None or parsed.username is not None
                or parsed.password is not None or parsed.path or parsed.query or parsed.fragment
                or not re.fullmatch(r"rest\.[a-z0-9-]+\.braze\.(?:com|eu)", host)):
            raise ValueError("Use the HTTPS Braze REST endpoint shown with your API key (rest.*.braze.com or rest.*.braze.eu)")
        return value


def _field_name(key: str) -> str:
    return "query_" + re.sub(r"[^a-zA-Z0-9_]+", "_", key).strip("_").lower()


def _make_config(name: str, op: Operation) -> type[BaseModel]:
    fields: dict[str, tuple[Any, Any]] = {}
    for path_name in re.findall(r"\{([^}]+)\}", op.path):
        fields[path_name] = (str, Field(..., title=path_name.replace("_", " ").title(), description="Braze path parameter"))
    for key, required, value_type, description in op.query:
        field_name = _field_name(key)
        if field_name in fields:
            continue
        fields[field_name] = (
            str if required else Optional[str],
            Field(... if required else None, title=key, description=f"{value_type}. {description}"[:500]),
        )
    fields["query_json"] = (Optional[str], Field(
        None, title="Additional Query Parameters JSON",
        description="Optional JSON object of extra Braze query parameters and filters.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    ))
    if op.body:
        fields["body_json"] = (Optional[str], Field(
            None, title="Request JSON",
            description="Braze request body as a JSON object. See the linked API reference for required fields and per-endpoint limits.",
            json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
        ))
    return create_model(
        "Braze" + "".join(part.title() for part in name.split("_")) + "Config",
        __module__=__name__,
        operation=(Literal[name], Field(name, title=op.label, json_schema_extra={
            "const": name, "ui:hidden": True, "x-category": op.category,
            "x-is-trigger": False, "x-display-name": op.label,
        })),
        **fields,
    )


CONFIG_MODELS = {name: _make_config(name, op) for name, op in OPERATIONS.items()}
globals().update({model.__name__: model for model in CONFIG_MODELS.values()})
BrazeConfig = Annotated[Union[tuple(CONFIG_MODELS.values())], Discriminator("operation")]


class BrazeNodeConfig(NodeConfig[BrazeConfig, BrazeApiKeyCredential]):
    model_config = ConfigDict(json_schema_extra={"x-agent-tool-provider": True})


class BrazeNode(WorkflowNode):
    integration_type = "automation-braze"
    connection_evidence = ConnectionEvidence(operation="list_campaigns", noun="campaigns")
    edit_examples = [
        "List Braze campaigns", "Track Braze users and events", "Send a Braze campaign",
        "List Braze Canvases", "Create a Braze catalog item",
    ]

    @classmethod
    def get_config_model(cls):
        return BrazeNodeConfig

    @staticmethod
    def _parse_json(raw: Optional[str], label: str) -> Optional[dict[str, Any]]:
        if raw is None or raw == "":
            return None
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{label} must be valid JSON") from exc
        if not isinstance(value, dict):
            raise ValueError(f"{label} must be a JSON object")
        return value

    @staticmethod
    def _query_value(value: Any) -> Any:
        if isinstance(value, list):
            return [BrazeNode._query_value(item) for item in value]
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, dict):
            return json.dumps(value, separators=(",", ":"))
        return "" if value is None else str(value)

    @staticmethod
    async def _request(method: str, endpoint: str, credential: BrazeApiKeyCredential,
                       params: dict[str, Any], body: Optional[dict[str, Any]]) -> Any:
        async with httpx.AsyncClient(timeout=45) as client:
            response = await client.request(
                method, f"{credential.rest_endpoint}{endpoint}",
                params=params or None, json=body,
                headers={"Authorization": f"Bearer {credential.api_key}",
                         "Accept": "application/json", "Content-Type": "application/json"},
            )
        if response.is_error:
            try:
                payload = response.json()
                detail = payload.get("message") or payload.get("error") if isinstance(payload, dict) else None
            except ValueError:
                detail = None
            raise ValueError(f"Braze API error {response.status_code}: {detail or 'request failed'}")
        if not response.content:
            return {"ok": True}
        try:
            return response.json()
        except ValueError as exc:
            raise ValueError(f"Braze returned invalid JSON ({response.status_code})") from exc

    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(self.config, BrazeNodeConfig):
            raise ValueError("Braze configuration required")
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a Braze REST API key")
        config = self.config.config
        op = OPERATIONS[config.operation]
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        path = op.path
        for path_name in re.findall(r"\{([^}]+)\}", path):
            path = path.replace("{" + path_name + "}", quote(str(values.pop(path_name)), safe=""))
        params = {key: self._query_value(value) for key, value in
                  (self._parse_json(values.pop("query_json", None), "Additional Query Parameters JSON") or {}).items()}
        for key, _, _, _ in op.query:
            field_name = _field_name(key)
            if field_name in values:
                params[key] = values.pop(field_name)
        body = self._parse_json(values.pop("body_json", None), "Request JSON")
        data = await self._request(op.method, path, credential, params, body)
        status = "partial" if isinstance(data, dict) and data.get("errors") else "success"
        return {"status": status, "operation": config.operation, "data": data}
