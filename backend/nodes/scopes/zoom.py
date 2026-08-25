"""Zoom operation → OAuth scope requirements.

Zoom's modern *granular* scopes read ``<resource>:<action>:<object>`` — e.g.
``meeting:read:list_meetings`` — and each one exists in up to three levels: the
bare user-level form (acts on the connected user's own resources), an ``:admin``
form (any user in the account), and a ``:master`` form (partner/reseller). Zoom
lists all applicable levels on an endpoint as ALTERNATIVES: holding any one of
them satisfies the call. ``ZoomOAuthCredential`` requests only bare user-level
scopes, so this table maps each operation to the user-level form.

Verified against Zoom's published OpenAPI documents (the ``x-granular-scopes``
extension on every operation in ``https://developers.zoom.us/api-hub/<product>/
methods/endpoints.json``), which is the same data rendered as "Granular Scopes"
in the API reference. Enforcement stays ``SUBSET``: the derived union must fit
inside the hand-written ``ZOOM_OAUTH_SCOPES`` list, which is NOT edited here.

Three quirks make this node's coverage unusually thin — 20 of 1640
operations are satisfiable by the scopes the node requests:

- **Granular scopes split writes three ways.** ``write`` means create only;
  update and delete have their own verbs (``meeting:update:meeting``,
  ``meeting:delete:meeting``). The requested list carries only the ``write``
  form, so every update/delete operation on meetings, webinars and users is
  unreachable.
- **Several requested scopes exist only at ``:admin`` level.** No endpoint
  accepts a bare ``user:read:list_users``, ``user:write:user`` or
  ``phone:read:list_call_logs`` — Zoom publishes those three only with the
  ``:admin`` suffix, so the requested user-level spellings match nothing.
- **Two requested scopes are not Zoom scopes at all.**
  ``cloud_recording:delete:meeting_recordings`` is a pluralization of the real
  ``cloud_recording:delete:meeting_recording``, and ``chat_message:write:message``
  does not exist — Team Chat sends need ``team_chat:write:user_message``.

Everything unsatisfiable is listed in ``unmapped`` with the scope Zoom actually
requires, grouped by product family. Those are reported, not fixed: widening
``ZOOM_OAUTH_SCOPES`` forces every connected user to re-authorize, so the batch
is decided deliberately rather than node by node.
"""

from __future__ import annotations

from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement


def _s(*scopes: str) -> ScopeRequirement:
    return ScopeRequirement(scopes=scopes)


# Operations whose required user-level granular scope is already requested by
# ``ZOOM_OAUTH_SCOPES``. These are the only ones that can run on a NoClick
# Zoom OAuth connection today.
_REQUIREMENTS: dict[str, ScopeRequirement] = {
    "get_meeting": _s("meeting:read:meeting"),
    "create_meeting": _s("meeting:write:meeting"),
    "list_meetings": _s("meeting:read:list_meetings"),
    "list_meeting_registrants": _s("meeting:read:list_registrants"),
    "add_meeting_registrant": _s("meeting:write:registrant"),
    "get_meeting_invitation": _s("meeting:read:invitation"),
    "get_past_meeting": _s("meeting:read:past_meeting"),
    "list_past_participants": _s("meeting:read:list_past_participants"),
    "get_webinar": _s("webinar:read:webinar"),
    "create_webinar": _s("webinar:write:webinar"),
    "list_webinars": _s("webinar:read:list_webinars"),
    "list_webinar_registrants": _s("webinar:read:list_registrants"),
    "add_webinar_registrant": _s("webinar:write:registrant"),
    "get_user": _s("user:read:user"),
    "list_user_recordings": _s("cloud_recording:read:list_user_recordings"),
    "get_meeting_recordings": _s("cloud_recording:read:list_recording_files"),
    "get_phone_user_call_history": _s("phone:read:list_call_logs"),
    "get_phone_user_call_logs": _s("phone:read:list_call_logs"),
    "get_user_call_history": _s("phone:read:list_call_logs"),
    "get_user_call_logs": _s("phone:read:list_call_logs"),
}


ZOOM_SCOPES = ScopeRegistry(
    provider="zoom",
    requirements=_REQUIREMENTS,
    unmapped=(
        # Zoom Phone (359) — MISSING SCOPES, in phone:*. Not one of the scopes named
        # below is in ZOOM_OAUTH_SCOPES, so every operation here fails with an invalid-
        # scope error. The scope shown is the user-level granular scope Zoom publishes
        # for that endpoint unless noted otherwise.
        "active_cr_phone_numbers",  # phone:update:carrier_number:admin  (admin-level only)
        "add_account_outbound_exception",  # phone:write:outbound_calling_rule:admin  (admin-level only)
        "add_audio_item",  # phone:write:audio
        "add_audio_items_batch",  # phone:write:batch_audios
        "add_auto_receptionist_call_handling",  # endpoint absent from Zoom's published spec
        "add_auto_receptionist_setting",  # phone:write:auto_receptionist_setting:admin  (admin-level only)
        "add_blocked_list_number",  # phone:write:blocked_list:admin  (admin-level only)
        "add_byoc_number",  # phone:write:byo_carrier_number:admin  (admin-level only)
        "add_byoc_numbers",  # phone:write:byo_carrier_number:admin  (admin-level only)
        "add_call_handling_setting",  # phone:write:call_handling_setting:admin  (admin-level only)
        "add_call_history_client_code",  # endpoint absent from Zoom's published spec
        "add_call_queue_call_handling",  # phone:write:call_handling_setting:admin  (admin-level only)
        "add_call_queue_custom_group_members",  # phone:write:call_queue_custom_group_member:admin  (admin-level only)
        "add_call_queue_managers",  # endpoint absent from Zoom's published spec
        "add_call_queue_members",  # phone:write:call_queue_member:admin  (admin-level only)
        "add_call_queue_setting",  # phone:write:call_queue_setting:admin  (admin-level only)
        "add_common_area",  # phone:write:common_area:admin  (admin-level only)
        "add_common_area_outbound_calling_exception_rule",  # phone:write:common_area_outbound_calling_rule:admin  (admin-level only)
        "add_common_area_outbound_exception",  # phone:write:common_area_outbound_calling_rule:admin  (admin-level only)
        "add_common_area_setting",  # phone:write:common_area_setting:admin  (admin-level only)
        "add_dial_by_name_directory_users",  # phone:write:directory:admin  (admin-level only)
        "add_emergency_address",  # phone:write:emergency_address:admin  (admin-level only)
        "add_emergency_service_location",  # phone:write:emergency_location:admin  (admin-level only)
        "add_extension_inbound_block_rule",  # phone:write:extension_inbound_block_rule
        "add_external_contact",  # phone:write:external_contact:admin  (admin-level only)
        "add_firmware_update_rule",  # phone:write:firmware_update_rule:admin  (admin-level only)
        "add_group_call_pickup_members",  # phone:write:call_pickup_group_member:admin  (admin-level only)
        "add_inbound_block_rule",  # phone:write:inbound_block_rule:admin  (admin-level only)
        "add_monitoring_group_members",  # phone:write:monitoring_group_member:admin  (admin-level only)
        "add_peering_numbers",  # phone:write:peering_number:admin  (admin-level only)
        "add_phone_alert_setting",  # phone:write:alert_setting:admin  (admin-level only)
        "add_phone_device",  # phone:write:device:admin  (admin-level only)
        "add_phone_role_members",  # phone:write:role_member:admin  (admin-level only)
        "add_phone_site_setting",  # phone:write:site_setting:admin  (admin-level only)
        "add_phone_user_customized_caller_id",  # phone:write:user_customized_number
        "add_phone_user_setting",  # phone:write:shared_setting
        "add_phone_zoom_room",  # phone:write:room:admin  (admin-level only)
        "add_private_directory_members",  # phone:write:private_directory_member:admin  (admin-level only)
        "add_provision_template",  # phone:write:provision_template:admin  (admin-level only)
        "add_routing_rule",  # phone:write:routing_rule:admin  (admin-level only)
        "add_site_dial_by_name_directory_users",  # phone:write:directory:admin  (admin-level only)
        "add_site_outbound_caller_ids",  # phone:write:site_customized_number:admin  (admin-level only)
        "add_site_outbound_exception",  # phone:write:site_outbound_calling_rule:admin  (admin-level only)
        "add_slg_members",  # phone:write:shared_line_member:admin  (admin-level only)
        "add_slg_outbound_caller_ids",  # endpoint absent from Zoom's published spec
        "add_slg_policy",  # phone:write:shared_line_group_policy:admin  (admin-level only)
        "add_user_call_log_client_code",  # endpoint absent from Zoom's published spec
        "add_user_outbound_exception",  # phone:write:user_outbound_calling_rule:admin  (admin-level only)
        "assign_auto_receptionist_phone_numbers",  # phone:write:auto_receptionist_number:admin  (admin-level only)
        "assign_call_queue_phone_numbers",  # phone:write:call_queue_number:admin  (admin-level only)
        "assign_calling_plan_to_phone_zoom_room",  # phone:write:room_calling_plan:admin  (admin-level only)
        "assign_common_area_calling_plans",  # phone:write:common_area_calling_plan:admin  (admin-level only)
        "assign_common_area_phone_numbers",  # phone:write:common_area_number:admin  (admin-level only)
        "assign_phone_calling_plans",  # phone:write:calling_plan
        "assign_phone_entity_to_device",  # phone:write:device_extension:admin  (admin-level only)
        "assign_phone_number_to_phone_zoom_room",  # phone:write:room_phone_number:admin  (admin-level only)
        "assign_phone_numbers_to_user",  # phone:write:user_number
        "assign_slg_phone_numbers",  # phone:write:shared_line_group_number:admin  (admin-level only)
        "assign_sms_campaign_phone_numbers",  # phone:write:sms_campaign_number:admin  (admin-level only)
        "batch_add_emergency_service_locations",  # phone:write:batch_emergency_locations:admin  (admin-level only)
        "batch_update_phone_users",  # phone:update:batch_users:admin  (admin-level only)
        "create_auto_receptionist",  # phone:write:auto_receptionist:admin  (admin-level only)
        "create_call_queue",  # phone:write:call_queue:admin  (admin-level only)
        "create_call_queue_custom_group",  # phone:write:call_queue_custom_group:admin  (admin-level only)
        "create_cr_phone_numbers",  # phone:write:carrier_number:admin  (admin-level only)
        "create_fax_document",  # phone:write:send_fax
        "create_group_call_pickup",  # phone:write:call_pickup_group:admin  (admin-level only)
        "create_monitoring_group",  # phone:write:monitoring_group:admin  (admin-level only)
        "create_phone_setting_template",  # phone:write:setting_template:admin  (admin-level only)
        "create_phone_site",  # phone:write:site:admin  (admin-level only)
        "create_shared_line_group",  # phone:write:shared_line_group:admin  (admin-level only)
        "delete_account_outbound_exception",  # phone:delete:outbound_calling_rule:admin  (admin-level only)
        "delete_audio_item",  # phone:delete:audio
        "delete_auto_receptionist",  # phone:delete:auto_receptionist:admin  (admin-level only)
        "delete_auto_receptionist_call_handling",  # endpoint absent from Zoom's published spec
        "delete_auto_receptionist_setting",  # phone:delete:auto_receptionist_setting:admin  (admin-level only)
        "delete_blocked_list",  # phone:delete:blocked_list:admin  (admin-level only)
        "delete_call_handling_setting",  # phone:delete:call_handling_setting:admin  (admin-level only)
        "delete_call_history",  # endpoint absent from Zoom's published spec
        "delete_call_queue",  # phone:delete:call_queue:admin  (admin-level only)
        "delete_call_queue_call_handling",  # phone:delete:call_handling_setting:admin  (admin-level only)
        "delete_call_queue_custom_group",  # phone:delete:call_queue_custom_group:admin  (admin-level only)
        "delete_call_queue_setting",  # phone:delete:call_queue_setting:admin  (admin-level only)
        "delete_common_area",  # phone:delete:common_area:admin  (admin-level only)
        "delete_common_area_outbound_calling_exception_rule",  # phone:delete:common_area_outbound_calling_rule:admin  (admin-level only)
        "delete_common_area_outbound_exception",  # phone:delete:common_area_outbound_calling_rule:admin  (admin-level only)
        "delete_common_area_setting",  # phone:delete:common_area_setting:admin  (admin-level only)
        "delete_cr_phone_number",  # phone:delete:carrier_number:admin  (admin-level only)
        "delete_dial_by_name_directory_users",  # phone:delete:directory:admin  (admin-level only)
        "delete_emergency_address",  # phone:delete:emergency_address:admin  (admin-level only)
        "delete_emergency_service_location",  # phone:delete:emergency_location:admin  (admin-level only)
        "delete_extension_inbound_block_rule",  # phone:delete:extension_inbound_block_rule
        "delete_external_contact",  # phone:delete:external_contact:admin  (admin-level only)
        "delete_firmware_update_rule",  # phone:delete:firmware_update_rule:admin  (admin-level only)
        "delete_group_call_pickup",  # phone:delete:call_pickup_group:admin  (admin-level only)
        "delete_inbound_block_rule",  # phone:delete:inbound_block_rule:admin  (admin-level only)
        "delete_inbound_block_statistic",  # phone:delete:extension_inbound_block_rule_stat:admin  (admin-level only)
        "delete_monitoring_group",  # phone:delete:monitoring_group:admin  (admin-level only)
        "delete_peering_numbers",  # phone:delete:peering_number:admin  (admin-level only)
        "delete_phone_alert_setting",  # phone:delete:alert_setting:admin  (admin-level only)
        "delete_phone_device",  # phone:delete:device:admin  (admin-level only)
        "delete_phone_recording",  # endpoint absent from Zoom's published spec
        "delete_phone_role",  # phone:delete:role:admin  (admin-level only)
        "delete_phone_role_members",  # phone:delete:role_member:admin  (admin-level only)
        "delete_phone_site",  # phone:delete:site:admin  (admin-level only)
        "delete_phone_site_setting",  # phone:delete:site_setting:admin  (admin-level only)
        "delete_phone_user_call_log",  # phone:delete:call_log
        "delete_phone_user_customized_caller_id",  # phone:delete:user_customized_number
        "delete_phone_user_data",  # endpoint absent from Zoom's published spec
        "delete_phone_user_setting",  # phone:delete:shared_setting
        "delete_phone_user_voicemail",  # endpoint absent from Zoom's published spec
        "delete_private_directory_member",  # phone:delete:private_directory_member:admin  (admin-level only)
        "delete_provision_template",  # phone:delete:provision_template:admin  (admin-level only)
        "delete_routing_rule",  # phone:delete:routing_rule:admin  (admin-level only)
        "delete_shared_line_group",  # phone:delete:shared_line_group:admin  (admin-level only)
        "delete_site_dial_by_name_directory_users",  # phone:delete:directory:admin  (admin-level only)
        "delete_site_outbound_caller_ids",  # phone:delete:site_customized_number:admin  (admin-level only)
        "delete_site_outbound_exception",  # phone:delete:site_outbound_calling_rule:admin  (admin-level only)
        "delete_user_call_history",  # phone:delete:call_log
        "delete_user_call_log",  # phone:delete:call_log
        "delete_user_outbound_exception",  # phone:delete:user_outbound_calling_rule:admin  (admin-level only)
        "delete_voicemail",  # phone:delete:voicemail
        "download_phone_recording_transcript",  # phone:read:recording_transcript
        "duplicate_phone_role",  # phone:write:role:admin  (admin-level only)
        "get_account_call_history",  # phone:read:list_call_logs:admin  (admin-level only)
        "get_account_outbound_calling",  # phone:read:list_outbound_calling_rules:admin  (admin-level only)
        "get_audio_item",  # phone:read:audio
        "get_auto_receptionist",  # phone:read:auto_receptionist:admin  (admin-level only)
        "get_auto_receptionist_call_handling",  # phone:read:auto_receptionist_call_handling_setting:admin  (admin-level only)
        "get_auto_receptionist_ivr",  # phone:read:auto_receptionist_ivr:admin  (admin-level only)
        "get_auto_receptionist_policy",  # phone:read:auto_receptionist_policy:admin  (admin-level only)
        "get_auto_receptionist_settings",  # phone:read:auto_receptionist_setting:admin  (admin-level only)
        "get_blocked_list",  # phone:read:blocked_list:admin  (admin-level only)
        "get_call_handling_settings",  # phone:read:list_call_handling_settings:admin  (admin-level only)
        "get_call_history_detail",  # phone:read:call_log:admin  (admin-level only)
        "get_call_log_detail",  # phone:read:call_log:admin  (admin-level only)
        "get_call_log_metrics_details",  # phone:read:call_log:admin  (admin-level only)
        "get_call_qos",  # phone:read:call_qos:admin  (admin-level only)
        "get_call_queue",  # phone:read:call_queue:admin  (admin-level only)
        "get_call_queue_call_handling",  # phone:read:list_call_handling_settings:admin  (admin-level only)
        "get_call_queue_custom_group",  # phone:read:call_queue_custom_group:admin  (admin-level only)
        "get_call_queue_manual_outbound_caller_id",  # endpoint absent from Zoom's published spec
        "get_call_queue_policy",  # phone:read:call_queue_policy:admin  (admin-level only)
        "get_call_queue_recordings",  # phone:read:list_call_queue_recordings:admin  (admin-level only)
        "get_call_queue_settings",  # phone:read:call_queue_setting:admin  (admin-level only)
        "get_common_area",  # phone:read:common_area:admin  (admin-level only)
        "get_common_area_outbound_calling",  # phone:read:common_area_outbound_calling_rule:admin  (admin-level only)
        "get_common_area_outbound_calling_countries_regions",  # phone:read:common_area_outbound_calling_rule:admin  (admin-level only)
        "get_common_area_settings",  # phone:read:list_common_area_settings:admin  (admin-level only)
        "get_emergency_address",  # phone:read:emergency_address:admin  (admin-level only)
        "get_emergency_service_location",  # phone:read:emergency_location:admin  (admin-level only)
        "get_external_contact",  # phone:read:external_contact:admin  (admin-level only)
        "get_fax_log",  # phone:read:list_fax_log:admin  (admin-level only)
        "get_fax_log_file",  # phone:read:fax_log
        "get_firmware_update_rule",  # phone:read:firmware_update_rule:admin  (admin-level only)
        "get_group_call_pickup",  # phone:read:call_pickup_group:admin  (admin-level only)
        "get_monitoring_group",  # phone:read:monitoring_group:admin  (admin-level only)
        "get_phone_account_settings",  # phone:read:list_account_settings:admin  (admin-level only)
        "get_phone_alert_setting",  # phone:read:alert_setting:admin  (admin-level only)
        "get_phone_billing_account",  # endpoint absent from Zoom's published spec
        "get_phone_byoc_settings",  # endpoint absent from Zoom's published spec
        "get_phone_call_recordings",  # phone:read:call_recording
        "get_phone_device",  # phone:read:device:admin  (admin-level only)
        "get_phone_device_line_keys",  # phone:read:device_line_keys
        "get_phone_group",  # endpoint absent from Zoom's published spec
        "get_phone_number_details",  # phone:read:numbers:admin  (admin-level only)
        "get_phone_operation_logs_report",  # phone:read:operation_logs:admin  (admin-level only)
        "get_phone_recording",  # endpoint absent from Zoom's published spec
        "get_phone_recording_detail",  # endpoint absent from Zoom's published spec
        "get_phone_role",  # phone:read:role:admin  (admin-level only)
        "get_phone_setting_template",  # phone:read:setting_template:admin  (admin-level only)
        "get_phone_sip_trunk_settings",  # endpoint absent from Zoom's published spec
        "get_phone_site",  # phone:read:site:admin  (admin-level only)
        "get_phone_site_setting",  # phone:read:site_setting:admin  (admin-level only)
        "get_phone_user",  # phone:read:user
        "get_phone_user_line_keys",  # phone:read:line_keys
        "get_phone_user_profile_settings",  # endpoint absent from Zoom's published spec
        "get_phone_user_recordings",  # phone:read:list_recordings
        "get_phone_user_settings",  # phone:read:user_setting
        "get_phone_user_voicemails",  # phone:read:list_voicemails
        "get_phone_zoom_room",  # phone:read:room:admin  (admin-level only)
        "get_port_order_details",  # phone:read:ported_number:admin  (admin-level only)
        "get_provision_template",  # phone:read:provision_template:admin  (admin-level only)
        "get_routing_rule",  # phone:read:routing_rule:admin  (admin-level only)
        "get_shared_line_group",  # phone:read:shared_line_group:admin  (admin-level only)
        "get_site_outbound_calling",  # phone:read:site_outbound_calling_rule:admin  (admin-level only)
        "get_slg_policies",  # phone:read:shared_line_group_policy:admin  (admin-level only)
        "get_slg_policy",  # endpoint absent from Zoom's published spec
        "get_sms_by_message_id",  # phone:read:sms_message
        "get_sms_campaign",  # phone:read:sms_campaign:admin  (admin-level only)
        "get_sms_session_details",  # phone:read:sms_session
        "get_user_outbound_calling",  # phone:read:user_outbound_calling_rule:admin  (admin-level only)
        "get_voicemail",  # phone:read:voicemail
        "list_account_outbound_exceptions",  # phone:read:list_outbound_calling_rules:admin  (admin-level only)
        "list_account_voicemails",  # phone:read:list_voicemails:admin  (admin-level only)
        "list_audio_items",  # phone:read:list_audios
        "list_auto_receptionists",  # phone:read:list_auto_receptionists:admin  (admin-level only)
        "list_available_phone_numbers",  # phone:read:list_numbers:admin  (admin-level only)
        "list_blocked_list",  # phone:read:list_blocked_lists:admin  (admin-level only)
        "list_byoc_sip_trunks",  # phone:read:list_sip_trunks:admin  (admin-level only)
        "list_call_logs_metrics",  # phone:read:list_call_logs:admin  (admin-level only)
        "list_call_queue_custom_groups",  # phone:read:call_queue_custom_group:admin  (admin-level only)
        "list_call_queue_members",  # phone:read:list_call_queue_members:admin  (admin-level only)
        "list_call_queues",  # phone:read:list_call_queues:admin  (admin-level only)
        "list_carrier_peering_numbers",  # phone:read:list_peering_numbers:admin  (admin-level only)
        "list_common_area_activation_codes",  # phone:read:list_common_area_activation_codes:admin  (admin-level only)
        "list_common_area_outbound_calling_exception_rules",  # phone:read:common_area_outbound_calling_rule:admin  (admin-level only)
        "list_common_area_outbound_exceptions",  # phone:read:common_area_outbound_calling_rule:admin  (admin-level only)
        "list_common_areas",  # phone:read:common_area:admin  (admin-level only)
        "list_cr_phone_numbers",  # phone:read:list_carrier_numbers:admin  (admin-level only)
        "list_dial_by_name_directory_users",  # phone:read:directory:admin  (admin-level only)
        "list_emergency_addresses",  # phone:read:list_emergency_addresses:admin  (admin-level only)
        "list_emergency_service_locations",  # phone:read:list_emergency_locations:admin  (admin-level only)
        "list_extension_fax_logs",  # phone:read:list_fax_log
        "list_extension_inbound_block_rules",  # phone:read:list_extension_inbound_block_rules
        "list_external_contacts",  # phone:read:list_external_contacts:admin  (admin-level only)
        "list_fax_logs",  # phone:read:list_fax_log:admin  (admin-level only)
        "list_firmware_update_rules",  # phone:read:list_firmware_update_rules:admin  (admin-level only)
        "list_group_call_pickup",  # phone:read:list_call_pickup_groups:admin  (admin-level only)
        "list_group_call_pickup_members",  # phone:read:call_pickup_group_member:admin  (admin-level only)
        "list_inbound_block_rules",  # phone:read:list_inbound_block_rules:admin  (admin-level only)
        "list_inbound_block_statistics",  # phone:read:list_extension_inbound_block_rules_stat:admin  (admin-level only)
        "list_location_tracking",  # phone:read:list_tracked_locations:admin  (admin-level only)
        "list_monitoring_group_members",  # phone:read:list_monitoring_group_members:admin  (admin-level only)
        "list_monitoring_groups",  # phone:read:list_monitoring_groups:admin  (admin-level only)
        "list_past_calls",  # phone:read:list_call_logs:admin  (admin-level only)
        "list_peering_numbers",  # phone:read:list_peering_numbers:admin  (admin-level only)
        "list_phone_alert_settings",  # phone:read:list_alert_settings:admin  (admin-level only)
        "list_phone_billing_accounts",  # endpoint absent from Zoom's published spec
        "list_phone_device_firmwares",  # endpoint absent from Zoom's published spec
        "list_phone_devices",  # phone:read:list_devices:admin  (admin-level only)
        "list_phone_groups",  # endpoint absent from Zoom's published spec
        "list_phone_numbers",  # phone:read:list_numbers:admin  (admin-level only)
        "list_phone_plans",  # phone:read:list_calling_plans:admin  (admin-level only)
        "list_phone_recordings",  # phone:read:list_call_recordings:admin  (admin-level only)
        "list_phone_role_members",  # phone:read:role_member:admin  (admin-level only)
        "list_phone_roles",  # phone:read:list_roles:admin  (admin-level only)
        "list_phone_setting_templates",  # phone:read:list_setting_templates:admin  (admin-level only)
        "list_phone_sip_groups",  # phone:read:list_sip_groups:admin  (admin-level only)
        "list_phone_sip_trunks",  # phone:read:list_sip_trunks:admin  (admin-level only)
        "list_phone_sites",  # phone:read:list_sites:admin  (admin-level only)
        "list_phone_user_customized_caller_id",  # phone:read:list_user_customized_number
        "list_phone_user_recordings",  # phone:read:list_recordings
        "list_phone_users",  # phone:read:list_users:admin  (admin-level only)
        "list_phone_zoom_rooms",  # phone:read:list_rooms:admin  (admin-level only)
        "list_ported_numbers",  # phone:read:list_ported_numbers:admin  (admin-level only)
        "list_private_directory_members",  # phone:read:list_private_directory_members:admin  (admin-level only)
        "list_provision_templates",  # phone:read:list_provision_templates:admin  (admin-level only)
        "list_routing_rules",  # phone:read:list_routing_rules:admin  (admin-level only)
        "list_shared_line_groups",  # phone:read:list_shared_line_groups:admin  (admin-level only)
        "list_site_dial_by_name_directory_users",  # phone:read:directory:admin  (admin-level only)
        "list_site_outbound_caller_ids",  # phone:read:list_site_customized_number:admin  (admin-level only)
        "list_site_outbound_exceptions",  # phone:read:site_outbound_calling_rule:admin  (admin-level only)
        "list_slg_members",  # endpoint absent from Zoom's published spec
        "list_slg_outbound_caller_ids",  # endpoint absent from Zoom's published spec
        "list_sms_campaign_opt_status",  # phone:read:sms_campaign_number_opt_status:admin  (admin-level only)
        "list_sms_campaigns",  # phone:read:list_sms_campaigns:admin  (admin-level only)
        "list_sms_sessions",  # phone:read:list_sms_sessions
        "list_tracked_devices",  # endpoint absent from Zoom's published spec
        "list_unassigned_phone_numbers",  # phone:read:list_numbers:admin  (admin-level only)
        "list_unassigned_phone_zoom_rooms",  # phone:read:list_rooms:admin  (admin-level only)
        "list_updatable_firmwares",  # phone:read:list_firmwares:admin  (admin-level only)
        "list_user_outbound_exceptions",  # phone:read:user_outbound_calling_rule:admin  (admin-level only)
        "list_user_sms_sessions",  # phone:read:list_sms_sessions
        "list_user_voicemails",  # phone:read:list_voicemails
        "mark_number_blocked_for_all",  # phone:update:inbound_blocked_for_all:admin  (admin-level only)
        "opt_sms_campaign_members",  # phone:update:sms_campaign_number_opt_status:admin  (admin-level only)
        "reboot_phone_device",  # phone:write:reboot_device:admin  (admin-level only)
        "remove_all_call_queue_members",  # phone:delete:call_queue_member:admin  (admin-level only)
        "remove_all_slg_members",  # phone:delete:shared_line_member:admin  (admin-level only)
        "remove_call_queue_custom_group_member",  # phone:delete:call_queue_custom_group_member:admin  (admin-level only)
        "remove_call_queue_manager",  # endpoint absent from Zoom's published spec
        "remove_call_queue_member",  # phone:delete:call_queue_member:admin  (admin-level only)
        "remove_group_call_pickup_member",  # phone:delete:call_pickup_group_member:admin  (admin-level only)
        "remove_monitoring_group_member",  # phone:delete:monitoring_group_member:admin  (admin-level only)
        "remove_monitoring_group_members",  # phone:delete:monitoring_group_member:admin  (admin-level only)
        "remove_phone_zoom_room",  # phone:delete:room:admin  (admin-level only)
        "remove_slg_member",  # phone:delete:shared_line_member:admin  (admin-level only)
        "remove_slg_outbound_caller_ids",  # endpoint absent from Zoom's published spec
        "remove_slg_policy",  # phone:delete:shared_line_group_policy:admin  (admin-level only)
        "sync_phone_devices",  # phone:write:sync_device:admin  (admin-level only)
        "sync_sms_by_session",  # phone:read:sms_session
        "unassign_all_auto_receptionist_phone_numbers",  # phone:delete:auto_receptionist_number:admin  (admin-level only)
        "unassign_all_call_queue_phone_numbers",  # phone:delete:call_queue_number:admin  (admin-level only)
        "unassign_all_slg_phone_numbers",  # phone:delete:shared_line_group_number:admin  (admin-level only)
        "unassign_auto_receptionist_phone_number",  # phone:delete:auto_receptionist_number:admin  (admin-level only)
        "unassign_call_queue_phone_number",  # phone:delete:call_queue_number:admin  (admin-level only)
        "unassign_calling_plan_from_phone_zoom_room",  # phone:delete:room_calling_plan:admin  (admin-level only)
        "unassign_common_area_calling_plan",  # phone:delete:common_area_calling_plan:admin  (admin-level only)
        "unassign_common_area_phone_number",  # phone:delete:common_area_number:admin  (admin-level only)
        "unassign_phone_calling_plan",  # phone:delete:users_calling_plan
        "unassign_phone_entity_from_device",  # phone:delete:device_extension:admin  (admin-level only)
        "unassign_phone_number_from_phone_zoom_room",  # phone:delete:room_phone_number:admin  (admin-level only)
        "unassign_phone_number_from_user",  # phone:delete:user_number
        "unassign_slg_phone_number",  # phone:delete:shared_line_group_number:admin  (admin-level only)
        "unassign_sms_campaign_phone_number",  # phone:delete:sms_campaign_number:admin  (admin-level only)
        "update_account_outbound_calling",  # phone:update:outbound_calling_rule:admin  (admin-level only)
        "update_account_outbound_exception",  # phone:update:outbound_calling_rule:admin  (admin-level only)
        "update_audio_item",  # phone:update:audio
        "update_auto_receptionist",  # phone:update:auto_receptionist:admin  (admin-level only)
        "update_auto_receptionist_call_handling",  # phone:update:auto_receptionist_call_handling_setting:admin  (admin-level only)
        "update_auto_receptionist_ivr",  # phone:update:auto_receptionist_ivr:admin  (admin-level only)
        "update_auto_receptionist_policy",  # phone:update:auto_receptionist_policy:admin  (admin-level only)
        "update_auto_receptionist_setting",  # phone:update:auto_receptionist_setting:admin  (admin-level only)
        "update_blocked_list",  # phone:update:blocked_list:admin  (admin-level only)
        "update_byoc_number",  # endpoint absent from Zoom's published spec
        "update_call_handling_setting",  # phone:update:call_handling_setting:admin  (admin-level only)
        "update_call_queue",  # phone:update:call_queue:admin  (admin-level only)
        "update_call_queue_call_handling",  # phone:update:call_handling_setting:admin  (admin-level only)
        "update_call_queue_manual_outbound_caller_id",  # endpoint absent from Zoom's published spec
        "update_call_queue_policy",  # phone:update:call_queue_policy:admin  (admin-level only)
        "update_call_queue_recording_setting",  # endpoint absent from Zoom's published spec
        "update_call_queue_setting",  # phone:update:call_queue_setting:admin  (admin-level only)
        "update_common_area",  # phone:update:common_area:admin  (admin-level only)
        "update_common_area_outbound_calling",  # phone:update:common_area_outbound_calling_rule:admin  (admin-level only)
        "update_common_area_outbound_calling_countries_regions",  # phone:update:common_area_outbound_calling_rule:admin  (admin-level only)
        "update_common_area_outbound_calling_exception_rule",  # phone:update:common_area_outbound_calling_rule:admin  (admin-level only)
        "update_common_area_outbound_exception",  # phone:update:common_area_outbound_calling_rule:admin  (admin-level only)
        "update_common_area_setting",  # phone:update:common_area_setting:admin  (admin-level only)
        "update_device_provision_template",  # phone:update:device_provision_template:admin  (admin-level only)
        "update_emergency_address",  # phone:update:emergency_address:admin  (admin-level only)
        "update_emergency_service_location",  # phone:update:emergency_location:admin  (admin-level only)
        "update_external_contact",  # phone:update:external_contact:admin  (admin-level only)
        "update_firmware_update_rule",  # phone:update:firmware_update_rule:admin  (admin-level only)
        "update_group_call_pickup",  # phone:update:call_pickup_group:admin  (admin-level only)
        "update_inbound_block_rule",  # phone:update:inbound_block_rule:admin  (admin-level only)
        "update_monitoring_group",  # phone:update:monitoring_group:admin  (admin-level only)
        "update_peering_numbers",  # phone:update:peering_number:admin  (admin-level only)
        "update_phone_account_settings",  # endpoint absent from Zoom's published spec
        "update_phone_alert_setting",  # phone:patch:alert_setting:admin  (admin-level only)
        "update_phone_device",  # phone:update:device:admin  (admin-level only)
        "update_phone_device_line_keys",  # phone:update:device_line_keys
        "update_phone_number",  # phone:update:number:admin  (admin-level only)
        "update_phone_recording",  # phone:update:call_recording
        "update_phone_recording_status",  # endpoint absent from Zoom's published spec
        "update_phone_role",  # phone:update:role:admin  (admin-level only)
        "update_phone_setting_template",  # phone:update:setting_template:admin  (admin-level only)
        "update_phone_sip_trunk_settings",  # endpoint absent from Zoom's published spec
        "update_phone_site",  # phone:update:site:admin  (admin-level only)
        "update_phone_site_setting",  # phone:update:site_setting:admin  (admin-level only)
        "update_phone_user",  # phone:update:user
        "update_phone_user_customized_caller_id",  # endpoint absent from Zoom's published spec
        "update_phone_user_line_keys",  # phone:update:line_keys
        "update_phone_user_setting",  # phone:update:shared_setting
        "update_phone_user_settings",  # phone:update:user_setting
        "update_phone_zoom_room",  # phone:update:room:admin  (admin-level only)
        "update_private_directory_member",  # phone:update:private_directory_member:admin  (admin-level only)
        "update_provision_template",  # phone:update:provision_template:admin  (admin-level only)
        "update_routing_rule",  # phone:update:routing_rule:admin  (admin-level only)
        "update_shared_line_group",  # phone:update:shared_line_group:admin  (admin-level only)
        "update_site_outbound_calling",  # phone:update:site_outbound_calling_rule:admin  (admin-level only)
        "update_site_outbound_exception",  # phone:update:site_outbound_calling_rule:admin  (admin-level only)
        "update_site_unassigned_numbers",  # phone:update:site_number:admin  (admin-level only)
        "update_slg_policies",  # phone:update:shared_line_group_policy:admin  (admin-level only)
        "update_slg_policy",  # phone:update:shared_line_group_policy:admin  (admin-level only)
        "update_user_outbound_calling",  # phone:update:user_outbound_calling_rule:admin  (admin-level only)
        "update_user_outbound_exception",  # phone:update:user_outbound_calling_rule:admin  (admin-level only)
        "update_voicemail_read_status",  # phone:update:voicemail
        "upload_fax_file",  # phone:write:send_fax

        # Team Chat (75) — MISSING SCOPES, in team_chat:*, imchat:*. Not one of the
        # scopes named below is in ZOOM_OAUTH_SCOPES, so every operation here fails with
        # an invalid-scope error. The scope shown is the user-level granular scope Zoom
        # publishes for that endpoint unless noted otherwise.
        "add_legal_hold_matter",  # team_chat:write:legal_hold_matter:admin  (admin-level only)
        "add_mention_group_members",  # endpoint absent from Zoom's published spec
        "add_shared_space_members",  # team_chat:write:shared_space_members
        "batch_add_chat_channel_members",  # endpoint absent from Zoom's published spec
        "create_channel_mention_group",  # endpoint absent from Zoom's published spec
        "create_chat_channel",  # team_chat:write:user_channel
        "create_emoji_category",  # endpoint absent from Zoom's published spec
        "create_message_reminder",  # endpoint absent from Zoom's published spec
        "create_shared_space",  # team_chat:write:shared_space
        "delete_admin_channel",  # team_chat:delete:channel
        "delete_channel_mention_group",  # endpoint absent from Zoom's published spec
        "delete_chat_channel",  # team_chat:delete:user_channel
        "delete_chat_file",  # team_chat:delete:file
        "delete_chat_message",  # team_chat:delete:user_message
        "delete_emoji_category",  # endpoint absent from Zoom's published spec
        "delete_legal_hold_matter",  # team_chat:delete:legal_hold_matter:admin  (admin-level only)
        "delete_message_reminder",  # endpoint absent from Zoom's published spec
        "delete_shared_space",  # team_chat:delete:shared_space
        "demote_channel_administrators",  # endpoint absent from Zoom's published spec
        "demote_shared_space_admin",  # team_chat:delete:shared_space_administrators
        "download_legal_hold_files",  # team_chat:read:legal_hold_matter_file:admin  (admin-level only)
        "get_admin_channel",  # team_chat:read:channel
        "get_channel_mention_group",  # endpoint absent from Zoom's published spec
        "get_chat_channel",  # team_chat:read:user_channel
        "get_chat_file",  # team_chat:read:file
        "get_chat_message",  # team_chat:read:user_message
        "get_im_message",  # endpoint absent from Zoom's published spec
        "get_im_session",  # endpoint absent from Zoom's published spec
        "get_legal_hold_matter",  # endpoint absent from Zoom's published spec
        "get_shared_space",  # team_chat:read:shared_space
        "invite_channel_members_admin",  # team_chat:write:members
        "invite_chat_channel_invite",  # endpoint absent from Zoom's published spec
        "invite_chat_channel_members",  # team_chat:write:members
        "join_chat_channel",  # team_chat:write:member
        "leave_chat_channel",  # team_chat:delete:member
        "list_account_channels",  # team_chat:read:list_channels:admin  (admin-level only)
        "list_category_emojis",  # endpoint absent from Zoom's published spec
        "list_channel_administrators",  # endpoint absent from Zoom's published spec
        "list_channel_members_admin",  # team_chat:read:list_members
        "list_channel_mention_groups",  # endpoint absent from Zoom's published spec
        "list_chat_channel_members",  # team_chat:read:list_members
        "list_chat_channels",  # team_chat:read:list_user_channels
        "list_chat_files",  # endpoint absent from Zoom's published spec
        "list_emoji_categories",  # endpoint absent from Zoom's published spec
        "list_legal_hold_files",  # team_chat:read:list_legal_hold_matter_files:admin  (admin-level only)
        "list_legal_hold_matters",  # team_chat:read:list_legal_hold_matters:admin  (admin-level only)
        "list_mention_group_members",  # endpoint absent from Zoom's published spec
        "list_reminders",  # endpoint absent from Zoom's published spec
        "list_scheduled_chat_messages",  # endpoint absent from Zoom's published spec
        "list_shared_space_channels",  # team_chat:read:list_shared_space_channels
        "list_shared_space_members",  # team_chat:read:list_shared_space_members
        "list_shared_spaces",  # team_chat:read:list_shared_spaces
        "list_user_chat_messages",  # team_chat:read:list_user_messages
        "mark_chat_message_status",  # team_chat:update:message_status
        "move_shared_space_channels",  # team_chat:update:shared_space_channels
        "promote_channel_administrators",  # endpoint absent from Zoom's published spec
        "promote_shared_space_admins",  # team_chat:write:shared_space_administrators
        "react_chat_message",  # team_chat:update:message_emoji
        "remove_channel_member_admin",  # team_chat:delete:member
        "remove_chat_channel_member",  # team_chat:delete:member
        "remove_mention_group_member",  # endpoint absent from Zoom's published spec
        "remove_shared_space_member",  # team_chat:delete:shared_space_members
        "search_account_channels",  # team_chat:write:search_channels
        "search_chat_channels",  # team_chat:write:search_channels
        "send_chat_file",  # team_chat:write:message_files
        "send_chat_message",  # team_chat:write:user_message
        "send_im_message",  # imchat:write  (classic scope; no granular equivalent published)
        "transfer_channel_owner",  # team_chat:update:channel_owner:admin  (admin-level only)
        "transfer_shared_space_owner",  # team_chat:update:shared_space_owner
        "update_admin_channel",  # team_chat:update:channel
        "update_channel_mention_group",  # endpoint absent from Zoom's published spec
        "update_chat_channel",  # team_chat:update:user_channel
        "update_chat_message",  # team_chat:update:user_message
        "update_legal_hold_matter",  # team_chat:update:legal_hold_matter:admin  (admin-level only)
        "update_shared_space",  # team_chat:update:shared_space

        # Webinars (46) — MISSING SCOPES, in webinar:*. Not one of the scopes named
        # below is in ZOOM_OAUTH_SCOPES, so every operation here fails with an invalid-
        # scope error. The scope shown is the user-level granular scope Zoom publishes
        # for that endpoint unless noted otherwise.
        "add_webinar_panelists",  # webinar:write:panelist
        "batch_add_webinar_registrants",  # webinar:write:batch_registrants
        "create_webinar_branding_name_tag",  # webinar:write:branding_name_tag
        "create_webinar_invite_links",  # webinar:write:invite_links
        "create_webinar_poll",  # webinar:write:poll
        "create_webinar_template",  # webinar:write:template
        "delete_webinar",  # webinar:delete:webinar
        "delete_webinar_branding_banner",  # endpoint absent from Zoom's published spec
        "delete_webinar_branding_name_tags",  # webinar:delete:branding_name_tag
        "delete_webinar_branding_virtual_backgrounds",  # webinar:delete:branding_virtual_background
        "delete_webinar_branding_wallpaper",  # webinar:delete:branding_wallpaper
        "delete_webinar_poll",  # webinar:delete:poll
        "delete_webinar_registrant",  # webinar:delete:registrant
        "delete_webinar_survey",  # webinar:delete:survey
        "get_webinar_absentees",  # webinar:read:list_absentees
        "get_webinar_branding",  # webinar:read:branding
        "get_webinar_live_streaming_token",  # webinar:read:live_streaming_token
        "get_webinar_livestream",  # webinar:read:livestream
        "get_webinar_local_recording_token",  # webinar:read:local_recording_token
        "get_webinar_poll",  # webinar:read:poll
        "get_webinar_registrant",  # webinar:read:registrant
        "get_webinar_registration_questions",  # webinar:read:list_registration_questions
        "get_webinar_survey",  # webinar:read:survey
        "list_past_webinar_instances",  # webinar:read:list_past_instances
        "list_past_webinar_participants",  # webinar:read:list_past_participants
        "list_past_webinar_polls",  # webinar:read:list_past_polls
        "list_past_webinar_qa",  # webinar:read:past_qa
        "list_webinar_panelists",  # webinar:read:list_panelists
        "list_webinar_polls",  # webinar:read:list_polls
        "list_webinar_templates",  # webinar:read:list_templates
        "list_webinar_tracking_sources",  # webinar:read:list_tracking_sources
        "remove_all_webinar_panelists",  # webinar:delete:panelist
        "remove_webinar_panelist",  # webinar:delete:panelist
        "set_webinar_branding_virtual_background_status",  # endpoint absent from Zoom's published spec
        "update_webinar",  # webinar:update:webinar
        "update_webinar_branding_name_tag",  # webinar:update:branding_name_tag
        "update_webinar_livestream",  # webinar:update:livestream
        "update_webinar_livestream_status",  # webinar:update:livestream_status
        "update_webinar_poll",  # webinar:update:poll
        "update_webinar_registrant_status",  # webinar:update:registrant_status
        "update_webinar_registration_questions",  # webinar:update:registration_question
        "update_webinar_status",  # webinar:update:status
        "update_webinar_survey",  # webinar:update:survey
        "upload_webinar_branding_banner",  # endpoint absent from Zoom's published spec
        "upload_webinar_branding_virtual_background",  # webinar:write:branding_virtual_background
        "upload_webinar_branding_wallpaper",  # webinar:write:branding_wallpaper

        # Meetings (40) — MISSING SCOPES, in meeting:*. Not one of the scopes named
        # below is in ZOOM_OAUTH_SCOPES, so every operation here fails with an invalid-
        # scope error. The scope shown is the user-level granular scope Zoom publishes
        # for that endpoint unless noted otherwise.
        "batch_add_meeting_registrants",  # meeting:write:batch_registrants
        "batch_create_meeting_polls",  # meeting:write:batch_polls
        "create_meeting_invite_links",  # meeting:write:invite_links
        "create_meeting_poll",  # meeting:write:poll
        "create_meeting_template",  # meeting:write:template
        "delete_live_meeting_chat_message",  # meeting:delete:live_meeting_chat_message
        "delete_meeting",  # meeting:delete:meeting
        "delete_meeting_poll",  # meeting:delete:poll
        "delete_meeting_registrant",  # meeting:delete:registrant
        "delete_meeting_summary",  # meeting:delete:summary
        "delete_meeting_survey",  # meeting:delete:survey
        "get_meeting_live_streaming_join_token",  # meeting:read:live_streaming_token
        "get_meeting_livestream",  # meeting:read:livestream
        "get_meeting_local_archiving_join_token",  # meeting:read:local_archiving_token:admin  (admin-level only)
        "get_meeting_local_recording_join_token",  # meeting:read:local_recording_token
        "get_meeting_poll",  # meeting:read:poll
        "get_meeting_registrant",  # meeting:read:registrant
        "get_meeting_registration_questions",  # meeting:read:list_registration_questions
        "get_meeting_summary",  # meeting:read:summary
        "get_meeting_survey",  # meeting:read:survey
        "get_meeting_token",  # meeting:read:token
        "list_meeting_polls",  # meeting:read:list_polls
        "list_meeting_summaries",  # meeting:read:list_summaries:admin  (admin-level only)
        "list_meeting_templates",  # meeting:read:list_templates
        "list_past_meeting_instances",  # meeting:read:list_past_instances
        "list_past_meeting_polls",  # meeting:read:list_poll_results
        "list_past_meeting_qa",  # meeting:read:past_qa
        "list_upcoming_meetings",  # meeting:read:list_upcoming_meetings
        "meeting_sip_dialing",  # meeting:write:sip_dialing
        "update_live_meeting_chat_message",  # meeting:update:live_meeting_chat_message
        "update_live_meeting_rtms_status",  # meeting:update:participant_rtms_app_status
        "update_meeting",  # meeting:update:meeting
        "update_meeting_livestream",  # meeting:update:livestream
        "update_meeting_livestream_status",  # meeting:update:livestream_status
        "update_meeting_poll",  # meeting:update:poll
        "update_meeting_registrant_status",  # meeting:update:registrant_status
        "update_meeting_registration_questions",  # meeting:update:registration_question
        "update_meeting_status",  # meeting:update:status
        "update_meeting_survey",  # meeting:update:survey
        "use_in_meeting_controls",  # meeting:update:in_meeting_controls

        # Users (36) — MISSING SCOPES, in user:*, tsp:*, pac:*. Not one of the scopes
        # named below is in ZOOM_OAUTH_SCOPES, so every operation here fails with an
        # invalid-scope error. The scope shown is the user-level granular scope Zoom
        # publishes for that endpoint unless noted otherwise.
        "add_user_assistants",  # user:write:assistant
        "add_user_tsp_account",  # tsp:write:tsp_account
        "check_user_email",  # user:read:email
        "check_vanity_name",  # user:read:pm_room
        "create_user",  # user:write:user:admin  (admin-level only)
        "delete_user",  # user:delete:user
        "delete_user_assistant",  # user:delete:assistant
        "delete_user_assistants",  # user:delete:assistant
        "delete_user_picture",  # user:write  (classic scope; no granular equivalent published)
        "delete_user_scheduler",  # user:delete:scheduler
        "delete_user_schedulers",  # user:delete:scheduler
        "delete_user_tsp_account",  # tsp:delete:tsp_account
        "delete_virtual_background",  # user:delete:virtual_background_files
        "get_collaboration_device",  # user:read:collaboration_device
        "get_user_permissions",  # user:read:list_permissions
        "get_user_settings",  # user:read:settings
        "get_user_token",  # user:read:token
        "get_user_tsp_account",  # tsp:read:tsp_account
        "get_user_zak",  # endpoint absent from Zoom's published spec
        "list_collaboration_devices",  # user:read:list_collaboration_devices
        "list_user_assistants",  # user:read:list_assistants
        "list_user_pac_accounts",  # pac:read:list_pac_accounts
        "list_user_schedulers",  # user:read:list_schedulers
        "list_user_tsp_accounts",  # tsp:read:list_tsp_accounts
        "list_users",  # user:read:list_users:admin  (admin-level only)
        "revoke_user_token",  # user:delete:token
        "switch_user_account",  # endpoint absent from Zoom's published spec
        "update_presence_status",  # user:update:presence_status
        "update_user",  # user:update:user
        "update_user_email",  # user:update:email
        "update_user_password",  # user:update:password
        "update_user_settings",  # user:update:settings
        "update_user_status",  # user:update:status
        "update_user_tsp_account",  # tsp:update:tsp_account
        "upload_user_picture",  # user:write:profile_picture
        "upload_virtual_background",  # user:write:virtual_background_files

        # Recordings (19) — MISSING SCOPES, in cloud_recording:*, archiving:*. Not one
        # of the scopes named below is in ZOOM_OAUTH_SCOPES, so every operation here
        # fails with an invalid-scope error. The scope shown is the user-level granular
        # scope Zoom publishes for that endpoint unless noted otherwise.
        "create_recording_registrant",  # cloud_recording:write:recording_registrant
        "delete_meeting_recordings",  # cloud_recording:delete:meeting_recording
        "delete_past_meeting_archive_files",  # archiving:delete:archived_files:admin  (admin-level only)
        "delete_recording_file",  # cloud_recording:delete:recording_file
        "get_archive_file_statistics",  # archiving:read:archived_file_statistics:admin  (admin-level only)
        "get_past_meeting_archive_files",  # archiving:read:archived_files
        "get_recording_analytics_details",  # cloud_recording:read:recording_analytics_details
        "get_recording_analytics_summary",  # cloud_recording:read:recording_analytics_summary
        "get_recording_registrant_questions",  # cloud_recording:read:registration_questions
        "get_recording_settings",  # cloud_recording:read:recording_settings
        "list_account_recordings",  # endpoint absent from Zoom's published spec
        "list_archive_files",  # archiving:read:list_archived_files:admin  (admin-level only)
        "list_recording_registrants",  # cloud_recording:read:list_recording_registrants
        "recover_meeting_recordings",  # cloud_recording:update:recover_meeting_recordings
        "recover_recording_file",  # cloud_recording:update:recover_single_recording
        "update_archive_file",  # archiving:update:archived_file_auto_delete_status
        "update_recording_registrant_questions",  # cloud_recording:update:registration_questions
        "update_recording_registrant_status",  # cloud_recording:update:registrant_status
        "update_recording_settings",  # cloud_recording:update:recording_settings

        # Contact Center (281) — MISSING SCOPES, in contact_center:*. Not one of the
        # scopes named below is in ZOOM_OAUTH_SCOPES, so every operation here fails with
        # an invalid-scope error. The scope shown is the user-level granular scope Zoom
        # publishes for that endpoint unless noted otherwise.
        "cc_add_contact",  # contact_center:write:outbound_campaign_contacts:admin  (admin-level only)
        "cc_add_dnc_phones",  # contact_center:write:outbound_campaign_dnc_list_phones:admin  (admin-level only)
        "cc_add_flow_entry_points",  # contact_center:write:flow:admin  (admin-level only)
        "cc_add_user_skills",  # contact_center:write:user_skill:admin  (admin-level only)
        "cc_agent_leg_metrics",  # contact_center:read:agent_report:admin  (admin-level only)
        "cc_agent_status_history",  # contact_center:read:agent_status_report:admin  (admin-level only)
        "cc_agent_time_sheets",  # contact_center:read:agent_report:admin  (admin-level only)
        "cc_assign_inbox_queues",  # contact_center:write:inbox_queue:admin  (admin-level only)
        "cc_assign_inbox_users",  # contact_center:write:inbox_user:admin  (admin-level only)
        "cc_assign_queue_agents",  # contact_center:write:queue_agent:admin  (admin-level only)
        "cc_assign_queue_disposition_sets",  # contact_center:write:queue_disposition_set:admin  (admin-level only)
        "cc_assign_queue_dispositions",  # contact_center:write:queue disposition:admin  (admin-level only)
        "cc_assign_queue_interrupt_menu",  # contact_center:update:queue:admin  (admin-level only)
        "cc_assign_queue_supervisors",  # contact_center:delete:queue_supervisor:admin  (admin-level only)
        "cc_assign_queue_teams",  # contact_center:write:queue_team:admin  (admin-level only)
        "cc_assign_region_users",  # contact_center:write:region_user:admin  (admin-level only)
        "cc_assign_role_users",  # contact_center:write:role_user:admin  (admin-level only)
        "cc_assign_team_agents",  # contact_center:write:team:admin  (admin-level only)
        "cc_assign_team_supervisors",  # contact_center:write:team:admin  (admin-level only)
        "cc_batch_create_contacts",  # contact_center:write:address_book_contact:admin  (admin-level only)
        "cc_batch_create_queues",  # contact_center:write:queue:admin  (admin-level only)
        "cc_batch_create_users",  # contact_center:write:batch_users:admin  (admin-level only)
        "cc_batch_delete_contacts",  # contact_center:delete:address_book_contact:admin  (admin-level only)
        "cc_batch_delete_queues",  # contact_center:delete:queue:admin  (admin-level only)
        "cc_batch_delete_users",  # contact_center:delete:batch_users:admin  (admin-level only)
        "cc_batch_update_contact_lists",  # contact_center:update:outbound_campaign_contactlist:admin  (admin-level only)
        "cc_batch_update_contacts",  # contact_center:update:address_book_contact:admin  (admin-level only)
        "cc_batch_update_user_status",  # contact_center:write:batch_users:admin  (admin-level only)
        "cc_batch_update_users",  # contact_center:update:batch_users:admin  (admin-level only)
        "cc_control_engagement_recording",  # contact_center:update:engagement_recording_control:admin  (admin-level only)
        "cc_control_recording",  # contact_center:update:engagement_recording_control:admin  (admin-level only)
        "cc_create_address_book",  # contact_center:write:address_book:admin  (admin-level only)
        "cc_create_address_book_custom_field",  # contact_center:write:address_book_custom_field:admin  (admin-level only)
        "cc_create_address_book_unit",  # contact_center:write:address_book_unit:admin  (admin-level only)
        "cc_create_agent_routing_profile",  # contact_center:write:agent_routing_profile:admin  (admin-level only)
        "cc_create_agent_status",  # contact_center:write:system_status:admin  (admin-level only)
        "cc_create_asset",  # contact_center:write:asset_library:admin  (admin-level only)
        "cc_create_asset_category",  # contact_center:write:asset_library:admin  (admin-level only)
        "cc_create_business_hours",  # contact_center:write:business_hour:admin  (admin-level only)
        "cc_create_campaign",  # contact_center:write:outbound_campaign:admin  (admin-level only)
        "cc_create_closure",  # contact_center:write:closure_hour:admin  (admin-level only)
        "cc_create_consumer_routing_profile",  # contact_center:write:consumer_routing_profile:admin  (admin-level only)
        "cc_create_contact",  # contact_center:write:address_book_contact:admin  (admin-level only)
        "cc_create_contact_list",  # contact_center:write:outbound_campaign_contactlist:admin  (admin-level only)
        "cc_create_disposition",  # contact_center:write:disposition:admin  (admin-level only)
        "cc_create_disposition_set",  # contact_center:write:disposition_set:admin  (admin-level only)
        "cc_create_engagement",  # contact_center:write:engagement:admin  (admin-level only)
        "cc_create_flow",  # contact_center:write:flow:admin  (admin-level only)
        "cc_create_inbox",  # contact_center:write:inbox:admin  (admin-level only)
        "cc_create_queue",  # contact_center:write:queue:admin  (admin-level only)
        "cc_create_region",  # contact_center:write:region:admin  (admin-level only)
        "cc_create_role",  # contact_center:write:role:admin  (admin-level only)
        "cc_create_skill",  # contact_center:write:skill:admin  (admin-level only)
        "cc_create_skill_category",  # contact_center:write:skill_category:admin  (admin-level only)
        "cc_create_team",  # contact_center:write:team:admin  (admin-level only)
        "cc_create_user",  # contact_center:write:user:admin  (admin-level only)
        "cc_create_user_template",  # contact_center:write:user_templates:admin  (admin-level only)
        "cc_create_variable",  # contact_center:write:variable:admin  (admin-level only)
        "cc_create_variable_group",  # contact_center:write:variable_group:admin  (admin-level only)
        "cc_delete_address_book",  # contact_center:delete:address_book:admin  (admin-level only)
        "cc_delete_address_book_custom_field",  # contact_center:delete:address_book_custom_field:admin  (admin-level only)
        "cc_delete_address_book_unit",  # contact_center:delete:address_book_unit:admin  (admin-level only)
        "cc_delete_agent_routing_profile",  # contact_center:delete:agent_routing_profile:admin  (admin-level only)
        "cc_delete_agent_status",  # contact_center:delete:system_status:admin  (admin-level only)
        "cc_delete_asset",  # contact_center:delete:asset_library:admin  (admin-level only)
        "cc_delete_asset_category",  # contact_center:delete:asset_library:admin  (admin-level only)
        "cc_delete_asset_items",  # contact_center:write:asset_library:admin  (admin-level only)
        "cc_delete_business_hours",  # contact_center:delete:business_hour:admin  (admin-level only)
        "cc_delete_campaign",  # contact_center:delete:outbound_campaign:admin  (admin-level only)
        "cc_delete_closure",  # contact_center:delete:closure_hour:admin  (admin-level only)
        "cc_delete_consumer_routing_profile",  # contact_center:delete:consumer_routing_profile:admin  (admin-level only)
        "cc_delete_contact",  # contact_center:delete:address_book_contact:admin  (admin-level only)
        "cc_delete_contact_list",  # contact_center:delete:outbound_campaign_contactlist:admin  (admin-level only)
        "cc_delete_disposition",  # contact_center:delete:disposition:admin  (admin-level only)
        "cc_delete_disposition_set",  # contact_center:delete:disposition_set:admin  (admin-level only)
        "cc_delete_dnc_phones",  # contact_center:delete:outbound_campaign_dnc_list_phones:admin  (admin-level only)
        "cc_delete_engagement_recordings",  # contact_center:delete:recording:admin  (admin-level only)
        "cc_delete_flow",  # contact_center:delete:flow:admin  (admin-level only)
        "cc_delete_flow_entry_points",  # contact_center:delete:flow:admin  (admin-level only)
        "cc_delete_inbox_message",  # contact_center:delete:inbox_message:admin  (admin-level only)
        "cc_delete_inbox_messages",  # contact_center:delete:inbox_messages:admin  (admin-level only)
        "cc_delete_inboxes",  # contact_center:delete:inbox:admin  (admin-level only)
        "cc_delete_inboxes_messages",  # contact_center:delete:inbox_messages:admin  (admin-level only)
        "cc_delete_queue",  # contact_center:delete:queue:admin  (admin-level only)
        "cc_delete_queue_callback_attendee",  # contact_center:delete:queue:admin  (admin-level only)
        "cc_delete_queue_interrupt_menu",  # contact_center:delete:queue:admin  (admin-level only)
        "cc_delete_queue_recordings",  # contact_center:delete:recording:admin  (admin-level only)
        "cc_delete_recording",  # contact_center:delete:recording:admin  (admin-level only)
        "cc_delete_region",  # contact_center:delete:region:admin  (admin-level only)
        "cc_delete_role",  # contact_center:delete:role:admin  (admin-level only)
        "cc_delete_role_privileges",  # contact_center:delete:role:admin  (admin-level only)
        "cc_delete_role_user",  # contact_center:delete:role_user:admin  (admin-level only)
        "cc_delete_skill",  # contact_center:delete:skill:admin  (admin-level only)
        "cc_delete_skill_category",  # contact_center:delete:skill_category:admin  (admin-level only)
        "cc_delete_team",  # contact_center:delete:team:admin  (admin-level only)
        "cc_delete_user",  # contact_center:delete:user:admin  (admin-level only)
        "cc_delete_user_recordings",  # contact_center:delete:recording:admin  (admin-level only)
        "cc_delete_user_template",  # contact_center:delete:user_templates:admin  (admin-level only)
        "cc_delete_variable",  # contact_center:delete:variable:admin  (admin-level only)
        "cc_delete_variable_group",  # contact_center:delete:variable_group:admin  (admin-level only)
        "cc_delete_variable_log",  # contact_center:delete:variable_log:admin  (admin-level only)
        "cc_duplicate_asset",  # contact_center:write:asset_library:admin  (admin-level only)
        "cc_duplicate_role",  # contact_center:write:role:admin  (admin-level only)
        "cc_export_flow",  # contact_center:read:flow:admin  (admin-level only)
        "cc_get_address_book",  # contact_center:read:address_book:admin  (admin-level only)
        "cc_get_address_book_custom_field",  # contact_center:read:address_book_custom_field:admin  (admin-level only)
        "cc_get_address_book_unit",  # contact_center:read:address_book_unit:admin  (admin-level only)
        "cc_get_agent_routing_profile",  # contact_center:read:agent_routing_profile:admin  (admin-level only)
        "cc_get_agent_status",  # contact_center:read:system_status:admin  (admin-level only)
        "cc_get_asset",  # contact_center:read:asset_library:admin  (admin-level only)
        "cc_get_asset_category",  # contact_center:read:asset_library:admin  (admin-level only)
        "cc_get_business_hours",  # contact_center:read:business_hour:admin  (admin-level only)
        "cc_get_campaign",  # contact_center:read:outbound_campaign:admin  (admin-level only)
        "cc_get_closure",  # contact_center:read:closure_hour:admin  (admin-level only)
        "cc_get_consumer_routing_profile",  # contact_center:read:consumer_routing_profile:admin  (admin-level only)
        "cc_get_contact",  # contact_center:read:address_book_contact:admin  (admin-level only)
        "cc_get_contact_custom_fields",  # contact_center:read:address_book_custom_field:admin  (admin-level only)
        "cc_get_contact_list",  # contact_center:read:outbound_campaign_contactlist:admin  (admin-level only)
        "cc_get_disposition",  # contact_center:read:disposition:admin  (admin-level only)
        "cc_get_disposition_set",  # contact_center:read:disposition_set:admin  (admin-level only)
        "cc_get_engagement",  # contact_center:read:engagement:admin  (admin-level only)
        "cc_get_engagement_attachments",  # contact_center:read:attachment:admin  (admin-level only)
        "cc_get_engagement_events",  # contact_center:read:engagement:admin  (admin-level only)
        "cc_get_engagement_note",  # contact_center:read:note:admin  (admin-level only)
        "cc_get_engagement_recording_status",  # contact_center:read:engagement_recording_status:admin  (admin-level only)
        "cc_get_engagement_recordings",  # contact_center:read:list_recordings:admin  (admin-level only)
        "cc_get_engagement_survey",  # contact_center:read:engagement:admin  (admin-level only)
        "cc_get_flow",  # contact_center:read:flow:admin  (admin-level only)
        "cc_get_historical_dataset",  # endpoint absent from Zoom's published spec
        "cc_get_historical_log",  # endpoint absent from Zoom's published spec
        "cc_get_inbox",  # contact_center:read:inbox:admin  (admin-level only)
        "cc_get_inbox_email_notifications",  # contact_center:read:inbox:admin  (admin-level only)
        "cc_get_note",  # contact_center:read:note:admin  (admin-level only)
        "cc_get_queue",  # contact_center:read:queue:admin  (admin-level only)
        "cc_get_queue_operating_hours",  # contact_center:read:queue_operating_hours:admin  (admin-level only)
        "cc_get_region",  # contact_center:read:region:admin  (admin-level only)
        "cc_get_role",  # contact_center:read:role:admin  (admin-level only)
        "cc_get_role_users",  # contact_center:read:list_role_users:admin  (admin-level only)
        "cc_get_skill",  # contact_center:read:skill:admin  (admin-level only)
        "cc_get_skill_category",  # contact_center:read:skill_category:admin  (admin-level only)
        "cc_get_team",  # contact_center:read:team:admin  (admin-level only)
        "cc_get_user",  # contact_center:read:user:admin  (admin-level only)
        "cc_get_user_template",  # contact_center:read:user_templates:admin  (admin-level only)
        "cc_get_variable",  # contact_center:read:variable:admin  (admin-level only)
        "cc_get_variable_group",  # contact_center:read:variable_group:admin  (admin-level only)
        "cc_get_variable_log",  # contact_center:read:variable_log:admin  (admin-level only)
        "cc_hist_agent_performance",  # contact_center:read:dataset_agent_performance:admin  (admin-level only)
        "cc_hist_agent_timecard",  # contact_center:read:dataset_agent_timecard:admin  (admin-level only)
        "cc_hist_disposition",  # contact_center:read:dataset_disposition:admin  (admin-level only)
        "cc_hist_engagement",  # contact_center:read:dataset_engagement:admin  (admin-level only)
        "cc_hist_engagement_log",  # contact_center:read:engagement_log:admin  (admin-level only)
        "cc_hist_expert_assist",  # contact_center:read:dataset_expert_assist:admin  (admin-level only)
        "cc_hist_flow_performance",  # contact_center:read:dataset_flow_performance:admin  (admin-level only)
        "cc_hist_journey_log",  # contact_center:read:call_journey_log:admin  (admin-level only)
        "cc_hist_outbound_dialer_performance",  # contact_center:read:dataset_outbound_dialer_performance:admin  (admin-level only)
        "cc_hist_queue_performance",  # contact_center:read:dataset_queue_performance:admin  (admin-level only)
        "cc_historical_detail_metrics",  # contact_center:read:engagement_report:admin  (admin-level only)
        "cc_historical_queue_metrics",  # contact_center:read:queue_report:admin  (admin-level only)
        "cc_list_address_book_custom_fields",  # contact_center:read:address_book_custom_field:admin  (admin-level only)
        "cc_list_address_book_units",  # contact_center:read:list_address_book_units:admin  (admin-level only)
        "cc_list_address_books",  # contact_center:read:list_address_books:admin  (admin-level only)
        "cc_list_agent_routing_profiles",  # contact_center:read:agent_routing_profile:admin  (admin-level only)
        "cc_list_agent_statuses",  # contact_center:read:list_system_statues:admin  (admin-level only)
        "cc_list_all_notes",  # contact_center:read:list_notes:admin  (admin-level only)
        "cc_list_asset_categories",  # contact_center:read:asset_library:admin  (admin-level only)
        "cc_list_assets",  # contact_center:read:asset_library:admin  (admin-level only)
        "cc_list_business_hours",  # contact_center:read:list_business_hours:admin  (admin-level only)
        "cc_list_business_hours_flows",  # contact_center:read:business_hours_flow:admin  (admin-level only)
        "cc_list_business_hours_queues",  # contact_center:read:business_hours_queue:admin  (admin-level only)
        "cc_list_campaigns",  # contact_center:read:outbound_campaign:admin  (admin-level only)
        "cc_list_closure_flows",  # contact_center:read:clousre_hour_flow:admin  (admin-level only)
        "cc_list_closure_queues",  # contact_center:read:closure_hour_queue:admin  (admin-level only)
        "cc_list_closures",  # contact_center:read:list_closure_hours:admin  (admin-level only)
        "cc_list_consumer_routing_profiles",  # contact_center:read:consumer_routing_profile:admin  (admin-level only)
        "cc_list_contact_lists",  # contact_center:read:outbound_campaign_contactlist:admin  (admin-level only)
        "cc_list_contacts",  # contact_center:read:list_address_book_contacts:admin  (admin-level only)
        "cc_list_disposition_sets",  # contact_center:read:list_disposition_sets:admin  (admin-level only)
        "cc_list_dispositions",  # contact_center:read:list_dispositions:admin  (admin-level only)
        "cc_list_dnc_phones",  # contact_center:read:outbound_campaign_dnc_list_phones:admin  (admin-level only)
        "cc_list_email_logs",  # contact_center:read:engagement_log:admin  (admin-level only)
        "cc_list_engagement_notes",  # contact_center:read:list_notes:admin  (admin-level only)
        "cc_list_engagement_recordings",  # contact_center:read:list_recordings:admin  (admin-level only)
        "cc_list_engagements",  # contact_center:read:list_engagements:admin  (admin-level only)
        "cc_list_flow_entry_points",  # contact_center:read:flow:admin  (admin-level only)
        "cc_list_flows",  # contact_center:read:list_flows:admin  (admin-level only)
        "cc_list_flows_entry_points",  # contact_center:read:flow:admin  (admin-level only)
        "cc_list_inbox_messages",  # contact_center:read:inbox_messages:admin  (admin-level only)
        "cc_list_inbox_queues",  # contact_center:read:list_inbox_queues:admin  (admin-level only)
        "cc_list_inbox_users",  # contact_center:read:inbox_user:admin  (admin-level only)
        "cc_list_inboxes",  # contact_center:read:list_inboxes:admin  (admin-level only)
        "cc_list_inboxes_messages",  # contact_center:read:inbox_messages:admin  (admin-level only)
        "cc_list_messaging_logs",  # contact_center:read:messaging:admin  (admin-level only)
        "cc_list_notes",  # contact_center:read:list_notes:admin  (admin-level only)
        "cc_list_operation_logs",  # contact_center:read:operation_logs:admin  (admin-level only)
        "cc_list_queue_agents",  # contact_center:read:list_queue_agents:admin  (admin-level only)
        "cc_list_queue_callback_slots",  # contact_center:read:queue:admin  (admin-level only)
        "cc_list_queue_disposition_sets",  # contact_center:read:list_disposition_sets:admin  (admin-level only)
        "cc_list_queue_dispositions",  # contact_center:read:list_dispositions:admin  (admin-level only)
        "cc_list_queue_recordings",  # contact_center:read:list_recordings
        "cc_list_queue_supervisors",  # contact_center:delete:queue_supervisor:admin  (admin-level only)
        "cc_list_queues",  # contact_center:read:list_queues:admin  (admin-level only)
        "cc_list_recordings",  # contact_center:read:list_recordings:admin  (admin-level only)
        "cc_list_region_users",  # contact_center:read:list_region_users:admin  (admin-level only)
        "cc_list_regions",  # contact_center:read:list_regions:admin  (admin-level only)
        "cc_list_roles",  # contact_center:read:list_roles:admin  (admin-level only)
        "cc_list_skill_categories",  # contact_center:read:list_skill_categories:admin  (admin-level only)
        "cc_list_skill_users",  # contact_center:read:list_skill_users:admin  (admin-level only)
        "cc_list_skills",  # contact_center:read:list_skills:admin  (admin-level only)
        "cc_list_sms_logs",  # contact_center:read:sms_log:admin  (admin-level only)
        "cc_list_team_agents",  # contact_center:read:team:admin  (admin-level only)
        "cc_list_team_children",  # contact_center:read:team:admin  (admin-level only)
        "cc_list_team_parents",  # contact_center:read:team:admin  (admin-level only)
        "cc_list_team_supervisors",  # contact_center:read:team:admin  (admin-level only)
        "cc_list_teams",  # contact_center:read:team:admin  (admin-level only)
        "cc_list_user_devices",  # contact_center:read:user_device:admin  (admin-level only)
        "cc_list_user_queues",  # contact_center:read:list_user_queues:admin  (admin-level only)
        "cc_list_user_recordings",  # contact_center:read:list_recordings
        "cc_list_user_skills",  # contact_center:read:list_user_skills:admin  (admin-level only)
        "cc_list_user_templates",  # contact_center:read:user_templates:admin  (admin-level only)
        "cc_list_users",  # contact_center:read:list_users:admin  (admin-level only)
        "cc_list_variable_groups",  # contact_center:read:list_variable_groups:admin  (admin-level only)
        "cc_list_variable_logs",  # contact_center:read:list_variable_logs:admin  (admin-level only)
        "cc_list_variables",  # contact_center:read:list_variables:admin  (admin-level only)
        "cc_list_voice_call_logs",  # contact_center:read:voice_call_log:admin  (admin-level only)
        "cc_list_work_item_logs",  # contact_center:read:engagement_log:admin  (admin-level only)
        "cc_move_team",  # contact_center:update:team:admin  (admin-level only)
        "cc_opt_in_out_queues",  # contact_center:update:queue_agent:admin  (admin-level only)
        "cc_publish_flow",  # contact_center:update:flow:admin  (admin-level only)
        "cc_queue_agent_metrics",  # contact_center:read:agent_report:admin  (admin-level only)
        "cc_queue_agents_metrics",  # contact_center:read:agent_report:admin  (admin-level only)
        "cc_remove_user_skill",  # contact_center:delete:user_skill:admin  (admin-level only)
        "cc_schedule_queue_callback",  # contact_center:write:queue:admin  (admin-level only)
        "cc_send_message",  # contact_center:write:messaging:admin  (admin-level only)
        "cc_send_sms",  # contact_center:write:sms:admin  (admin-level only)
        "cc_send_user_command",  # contact_center:write:user_control:admin  (admin-level only)
        "cc_set_campaign_status",  # contact_center:update:outbound_campaign:admin  (admin-level only)
        "cc_unassign_inbox_queues",  # contact_center:delete:inbox_queue:admin  (admin-level only)
        "cc_unassign_inbox_users",  # contact_center:delete:inbox_user:admin  (admin-level only)
        "cc_unassign_queue_agent",  # contact_center:delete:queue_agent:admin  (admin-level only)
        "cc_unassign_queue_disposition",  # contact_center:delete:queue_disposition:admin  (admin-level only)
        "cc_unassign_queue_disposition_set",  # contact_center:delete:queue_disposition_set:admin  (admin-level only)
        "cc_unassign_queue_supervisor",  # contact_center:delete:queue_supervisor:admin  (admin-level only)
        "cc_unassign_queue_team",  # contact_center:delete:queue_team:admin  (admin-level only)
        "cc_unassign_queue_teams",  # contact_center:delete:queue_team:admin  (admin-level only)
        "cc_unassign_team_agents",  # contact_center:delete:team:admin  (admin-level only)
        "cc_unassign_team_supervisors",  # contact_center:delete:team:admin  (admin-level only)
        "cc_update_address_book",  # contact_center:update:address_book:admin  (admin-level only)
        "cc_update_address_book_custom_field",  # contact_center:update:address_book_custom_field:admin  (admin-level only)
        "cc_update_address_book_unit",  # contact_center:update:address_book_unit:admin  (admin-level only)
        "cc_update_agent_routing_profile",  # contact_center:update:agent_routing_profile:admin  (admin-level only)
        "cc_update_agent_status",  # contact_center:update:system_status:admin  (admin-level only)
        "cc_update_asset",  # contact_center:write:asset_library:admin  (admin-level only)
        "cc_update_asset_category",  # contact_center:write:asset_library:admin  (admin-level only)
        "cc_update_business_hours",  # contact_center:update:business_hour:admin  (admin-level only)
        "cc_update_campaign",  # contact_center:update:outbound_campaign:admin  (admin-level only)
        "cc_update_closure",  # contact_center:update:closure_hour:admin  (admin-level only)
        "cc_update_consumer_routing_profile",  # contact_center:update:consumer_routing_profile:admin  (admin-level only)
        "cc_update_contact",  # contact_center:update:address_book_contact:admin  (admin-level only)
        "cc_update_contact_list",  # contact_center:update:outbound_campaign_contactlist:admin  (admin-level only)
        "cc_update_disposition",  # contact_center:update:disposition:admin  (admin-level only)
        "cc_update_disposition_set",  # contact_center:update:disposition_set:admin  (admin-level only)
        "cc_update_engagement",  # contact_center:update:engagement:admin  (admin-level only)
        "cc_update_engagement_note",  # contact_center:update:note
        "cc_update_flow",  # contact_center:update:flow:admin  (admin-level only)
        "cc_update_inbox",  # contact_center:update:inbox:admin  (admin-level only)
        "cc_update_inbox_email_notification",  # contact_center:update:inbox:admin  (admin-level only)
        "cc_update_note",  # contact_center:update:note
        "cc_update_queue",  # contact_center:update:queue:admin  (admin-level only)
        "cc_update_queue_agent",  # contact_center:update:queue_agent:admin  (admin-level only)
        "cc_update_queue_interrupt",  # contact_center:update:queue:admin  (admin-level only)
        "cc_update_queue_operating_hours",  # contact_center:patch:queue_operating_hours:admin  (admin-level only)
        "cc_update_region",  # contact_center:udpate:region:admin  (admin-level only)
        "cc_update_role",  # contact_center:update:role:admin  (admin-level only)
        "cc_update_skill",  # contact_center:update:skill:admin  (admin-level only)
        "cc_update_skill_category",  # contact_center:update:skill_category:admin  (admin-level only)
        "cc_update_team",  # contact_center:update:team:admin  (admin-level only)
        "cc_update_user",  # contact_center:update:user:admin  (admin-level only)
        "cc_update_user_status",  # contact_center:update:user:admin  (admin-level only)
        "cc_update_user_template",  # contact_center:update:user_templates:admin  (admin-level only)
        "cc_update_variable",  # contact_center:update:variable:admin  (admin-level only)
        "cc_update_variable_group",  # contact_center:update:variable_group:admin  (admin-level only)

        # Triggers (96) — webhook event deliveries. Zoom pushes these to the node's
        # webhook URL; no API call is made, so no OAuth scope is consumed at run time.
        # The event subscription is configured on the Zoom app itself.
        "on_account_created",  # webhook event
        "on_account_disassociated",  # webhook event
        "on_account_settings_updated",  # webhook event
        "on_account_updated",  # webhook event
        "on_account_vanity_url_updated",  # webhook event
        "on_any_zoom_event",  # webhook event
        "on_chat_channel_created",  # webhook event
        "on_chat_channel_deleted",  # webhook event
        "on_chat_channel_member_invited",  # webhook event
        "on_chat_channel_member_joined",  # webhook event
        "on_chat_channel_member_left",  # webhook event
        "on_chat_channel_updated",  # webhook event
        "on_chat_message_deleted",  # webhook event
        "on_chat_message_sent",  # webhook event
        "on_chat_message_updated",  # webhook event
        "on_meeting_alert",  # webhook event
        "on_meeting_breakout_room_ended",  # webhook event
        "on_meeting_breakout_room_started",  # webhook event
        "on_meeting_chat_message_sent",  # webhook event
        "on_meeting_created",  # webhook event
        "on_meeting_deleted",  # webhook event
        "on_meeting_ended",  # webhook event
        "on_meeting_live_streaming_started",  # webhook event
        "on_meeting_live_streaming_stopped",  # webhook event
        "on_meeting_participant_admitted",  # webhook event
        "on_meeting_participant_jbh_joined",  # webhook event
        "on_meeting_participant_jbh_waiting",  # webhook event
        "on_meeting_participant_joined",  # webhook event
        "on_meeting_participant_joined_waiting_room",  # webhook event
        "on_meeting_participant_left",  # webhook event
        "on_meeting_participant_left_waiting_room",  # webhook event
        "on_meeting_participant_put_in_waiting_room",  # webhook event
        "on_meeting_participant_role_changed",  # webhook event
        "on_meeting_permanently_deleted",  # webhook event
        "on_meeting_registration_approved",  # webhook event
        "on_meeting_registration_cancelled",  # webhook event
        "on_meeting_registration_created",  # webhook event
        "on_meeting_registration_denied",  # webhook event
        "on_meeting_risk_alert",  # webhook event
        "on_meeting_sharing_ended",  # webhook event
        "on_meeting_sharing_started",  # webhook event
        "on_meeting_started",  # webhook event
        "on_meeting_summary_completed",  # webhook event
        "on_meeting_updated",  # webhook event
        "on_phone_callee_answered",  # webhook event
        "on_phone_callee_ended",  # webhook event
        "on_phone_callee_missed",  # webhook event
        "on_phone_callee_rejected",  # webhook event
        "on_phone_caller_connected",  # webhook event
        "on_phone_caller_ended",  # webhook event
        "on_phone_emergency_alert",  # webhook event
        "on_phone_recording_completed",  # webhook event
        "on_phone_recording_started",  # webhook event
        "on_phone_recording_stopped",  # webhook event
        "on_phone_sms_received",  # webhook event
        "on_phone_sms_sent",  # webhook event
        "on_phone_voicemail_received",  # webhook event
        "on_phone_voicemail_transcript_completed",  # webhook event
        "on_recording_batch_deleted",  # webhook event
        "on_recording_completed",  # webhook event
        "on_recording_deleted",  # webhook event
        "on_recording_paused",  # webhook event
        "on_recording_recovered",  # webhook event
        "on_recording_registration_approved",  # webhook event
        "on_recording_registration_created",  # webhook event
        "on_recording_resumed",  # webhook event
        "on_recording_started",  # webhook event
        "on_recording_stopped",  # webhook event
        "on_recording_transcript_completed",  # webhook event
        "on_recording_trashed",  # webhook event
        "on_user_activated",  # webhook event
        "on_user_created",  # webhook event
        "on_user_deactivated",  # webhook event
        "on_user_deleted",  # webhook event
        "on_user_disassociated",  # webhook event
        "on_user_invitation_accepted",  # webhook event
        "on_user_personal_notes_updated",  # webhook event
        "on_user_presence_status_updated",  # webhook event
        "on_user_settings_updated",  # webhook event
        "on_user_signed_in",  # webhook event
        "on_user_signed_out",  # webhook event
        "on_user_updated",  # webhook event
        "on_webinar_alert",  # webhook event
        "on_webinar_created",  # webhook event
        "on_webinar_deleted",  # webhook event
        "on_webinar_ended",  # webhook event
        "on_webinar_participant_joined",  # webhook event
        "on_webinar_participant_left",  # webhook event
        "on_webinar_registration_approved",  # webhook event
        "on_webinar_registration_cancelled",  # webhook event
        "on_webinar_registration_created",  # webhook event
        "on_webinar_registration_denied",  # webhook event
        "on_webinar_sharing_ended",  # webhook event
        "on_webinar_sharing_started",  # webhook event
        "on_webinar_started",  # webhook event
        "on_webinar_updated",  # webhook event

        # Zoom Events (80) — MISSING SCOPES, in zoom_events:*. Not one of the scopes
        # named below is in ZOOM_OAUTH_SCOPES, so every operation here fails with an
        # invalid-scope error. The scope shown is the user-level granular scope Zoom
        # publishes for that endpoint unless noted otherwise.
        "zoom_events_cancel_event",  # zoom_events:write:event
        "zoom_events_create_access_link",  # zoom_events:write:access_links
        "zoom_events_create_event",  # zoom_events:write:event
        "zoom_events_create_exhibitor",  # zoom_events:write:exhibitor
        "zoom_events_create_hub_host",  # zoom_events:write:hub_host
        "zoom_events_create_session",  # zoom_events:write:session
        "zoom_events_create_session_reservation",  # zoom_events:write:session_reservations
        "zoom_events_create_speaker",  # zoom_events:write:speaker
        "zoom_events_create_ticket_type",  # zoom_events:write:ticket_type
        "zoom_events_create_tickets",  # zoom_events:write:ticket
        "zoom_events_delete_access_link",  # zoom_events:delete:access_links
        "zoom_events_delete_event",  # zoom_events:delete:event
        "zoom_events_delete_exhibitor",  # zoom_events:delete:exhibitor
        "zoom_events_delete_session",  # zoom_events:delete:session
        "zoom_events_delete_session_reservation",  # zoom_events:delete:session_reservations
        "zoom_events_delete_speaker",  # zoom_events:delete:speaker
        "zoom_events_delete_ticket",  # zoom_events:delete:ticket
        "zoom_events_delete_ticket_type",  # zoom_events:delete:ticket_type
        "zoom_events_duplicate_event",  # zoom_events:write:event
        "zoom_events_event_action",  # zoom_events:write:event
        "zoom_events_get_access_link",  # zoom_events:read:access_links
        "zoom_events_get_attendance_report",  # endpoint absent from Zoom's published spec
        "zoom_events_get_attendee_engagement",  # endpoint absent from Zoom's published spec
        "zoom_events_get_chat_transcript_report",  # endpoint absent from Zoom's published spec
        "zoom_events_get_custom_report",  # endpoint absent from Zoom's published spec
        "zoom_events_get_event",  # zoom_events:read:event
        "zoom_events_get_exhibitor",  # zoom_events:read:exhibitor
        "zoom_events_get_registrations_report",  # endpoint absent from Zoom's published spec
        "zoom_events_get_session",  # zoom_events:read:session
        "zoom_events_get_session_attendance_report",  # endpoint absent from Zoom's published spec
        "zoom_events_get_session_join_token",  # zoom_events:read:session_token
        "zoom_events_get_session_livestream",  # zoom_events:read:session_livestream_config
        "zoom_events_get_session_recording",  # endpoint absent from Zoom's published spec
        "zoom_events_get_session_report",  # endpoint absent from Zoom's published spec
        "zoom_events_get_speaker",  # zoom_events:read:speaker
        "zoom_events_get_survey_report",  # zoom_events:read:list_session_surveys
        "zoom_events_get_ticket",  # zoom_events:read:ticket
        "zoom_events_list_access_links",  # zoom_events:read:list_access_links
        "zoom_events_list_attendee_actions",  # zoom_events:read:list_attendee_actions
        "zoom_events_list_coeditors",  # zoom_events:read:list_coeditors
        "zoom_events_list_email_send_status",  # zoom_events:read:list_emails_status
        "zoom_events_list_email_types",  # zoom_events:read:list_email_types
        "zoom_events_list_event_attendee_actions",  # zoom_events:read:list_attendee_actions
        "zoom_events_list_event_questions",  # zoom_events:read:list_registration_questions
        "zoom_events_list_events",  # zoom_events:read:list_events
        "zoom_events_list_exhibitors",  # zoom_events:read:list_exhibitors
        "zoom_events_list_hub_hosts",  # zoom_events:read:list_hub_hosts
        "zoom_events_list_hub_videos",  # zoom_events:read:list_hub_videos
        "zoom_events_list_hubs",  # zoom_events:read:list_hubs
        "zoom_events_list_registrants",  # zoom_events:read:list_registrants
        "zoom_events_list_session_attendee_actions",  # zoom_events:read:list_session_attendee_actions
        "zoom_events_list_session_attendees",  # zoom_events:read:list_session_attendees
        "zoom_events_list_session_interpreters",  # zoom_events:read:list_session_interpreters
        "zoom_events_list_session_polls",  # zoom_events:read:list_session_polls
        "zoom_events_list_session_recordings",  # endpoint absent from Zoom's published spec
        "zoom_events_list_session_reservations",  # zoom_events:read:list_session_reservations
        "zoom_events_list_sessions",  # zoom_events:read:list_sessions
        "zoom_events_list_speakers",  # zoom_events:read:list_speakers
        "zoom_events_list_sponsor_tiers",  # zoom_events:read:list_sponsor_tiers
        "zoom_events_list_ticket_type_questions",  # zoom_events:read:list_registration_questions
        "zoom_events_list_ticket_types",  # zoom_events:read:list_ticket_types
        "zoom_events_list_tickets",  # zoom_events:read:list_tickets
        "zoom_events_publish_event",  # zoom_events:write:event
        "zoom_events_remove_hub_host",  # zoom_events:delete:hub_host
        "zoom_events_update_access_link",  # zoom_events:update:access_links
        "zoom_events_update_attendee_actions",  # zoom_events:update:batch_attendee_actions
        "zoom_events_update_coeditors",  # zoom_events:write:coeditor
        "zoom_events_update_event",  # zoom_events:update:event
        "zoom_events_update_event_attendee_actions",  # zoom_events:update:batch_attendee_actions
        "zoom_events_update_event_questions",  # zoom_events:update:registraion_question
        "zoom_events_update_exhibitor",  # zoom_events:update:exhibitor
        "zoom_events_update_session",  # zoom_events:update:session
        "zoom_events_update_session_attendee_actions",  # zoom_events:update:batch_session_attendee_actions
        "zoom_events_update_session_interpreters",  # zoom_events:update:session_interpreter
        "zoom_events_update_session_livestream",  # zoom_events:update:session_livestream_config
        "zoom_events_update_session_polls",  # zoom_events:update:session_poll
        "zoom_events_update_speaker",  # zoom_events:update:speaker
        "zoom_events_update_ticket",  # zoom_events:write:ticket
        "zoom_events_update_ticket_type",  # zoom_events:update:ticket_type
        "zoom_events_update_ticket_type_questions",  # zoom_events:update:registraion_question

        # Zoom Rooms (56) — MISSING SCOPES, in zoom_rooms:*, room:*. Not one of the
        # scopes named below is in ZOOM_OAUTH_SCOPES, so every operation here fails with
        # an invalid-scope error. The scope shown is the user-level granular scope Zoom
        # publishes for that endpoint unless noted otherwise.
        "add_background_image_content",  # endpoint absent from Zoom's published spec
        "add_content_folder",  # endpoint absent from Zoom's published spec
        "assign_room_tags",  # endpoint absent from Zoom's published spec
        "change_rooms_location_parent",  # zoom_rooms:update:location:admin  (admin-level only)
        "change_zoom_room_location",  # zoom_rooms:update:room_location:admin  (admin-level only)
        "control_zoom_room",  # zoom_rooms:update:room_control:admin  (admin-level only)
        "create_device_profile",  # endpoint absent from Zoom's published spec
        "create_digital_signage_playlist",  # zoom_rooms:write:digital_signage_library_playlists:admin  (admin-level only)
        "create_room_tag",  # zoom_rooms:write:tag:admin  (admin-level only)
        "create_rooms_location",  # zoom_rooms:write:location:admin  (admin-level only)
        "create_zoom_room",  # zoom_rooms:write:room:admin  (admin-level only)
        "delete_content_folder",  # endpoint absent from Zoom's published spec
        "delete_content_library_item",  # endpoint absent from Zoom's published spec
        "delete_device_profile",  # endpoint absent from Zoom's published spec
        "delete_digital_signage_playlist",  # zoom_rooms:write:digital_signage_library_playlists:admin  (admin-level only)
        "delete_room_tag",  # zoom_rooms:delete:tag:admin  (admin-level only)
        "delete_rooms_location",  # zoom_rooms:write:location:admin  (admin-level only)
        "delete_zoom_room",  # zoom_rooms:delete:room:admin  (admin-level only)
        "delete_zoom_room_device",  # zoom_rooms:delete:device:admin  (admin-level only)
        "get_device_profile",  # endpoint absent from Zoom's published spec
        "get_digital_signage_playlist",  # zoom_rooms:read:digital_signage_library_playlists:admin  (admin-level only)
        "get_room_tag",  # endpoint absent from Zoom's published spec
        "get_rooms_account_profile",  # zoom_rooms:read:account_profile:admin  (admin-level only)
        "get_rooms_account_settings",  # zoom_rooms:read:account_settings:admin  (admin-level only)
        "get_rooms_location_profile",  # zoom_rooms:read:location:admin  (admin-level only)
        "get_rooms_location_settings",  # zoom_rooms:read:location_settings:admin  (admin-level only)
        "get_rooms_location_structure",  # zoom_rooms:read:location_hierarchy:admin  (admin-level only)
        "get_zoom_room_profile",  # zoom_rooms:read:room:admin  (admin-level only)
        "get_zoom_room_sensor_data",  # zoom_rooms:read:sensor_data:admin  (admin-level only)
        "get_zoom_room_settings",  # zoom_rooms:read:room_settings:admin  (admin-level only)
        "list_calendar_resources",  # endpoint absent from Zoom's published spec
        "list_calendar_services",  # endpoint absent from Zoom's published spec
        "list_content_library",  # endpoint absent from Zoom's published spec
        "list_device_profiles",  # endpoint absent from Zoom's published spec
        "list_digital_signage_contents",  # room:read:admin  (classic scope; no granular equivalent published)
        "list_digital_signage_playlists",  # zoom_rooms:read:digital_signage_library_playlists:admin  (admin-level only)
        "list_playlist_rooms",  # zoom_rooms:read:digital_signage_library_playlists:admin  (admin-level only)
        "list_room_tags",  # zoom_rooms:read:list_tags:admin  (admin-level only)
        "list_rooms_locations",  # zoom_rooms:read:list_locations:admin  (admin-level only)
        "list_zoom_room_devices",  # zoom_rooms:read:list_devices:admin  (admin-level only)
        "list_zoom_rooms",  # zoom_rooms:read:list_rooms:admin  (admin-level only)
        "unassign_room_tags",  # zoom_rooms:delete:room_tag:admin  (admin-level only)
        "update_content_library_item",  # endpoint absent from Zoom's published spec
        "update_device_profile",  # endpoint absent from Zoom's published spec
        "update_digital_signage_playlist",  # zoom_rooms:write:digital_signage_library_playlists:admin  (admin-level only)
        "update_emergency_content",  # zoom_rooms:update:room_controls:admin  (admin-level only)
        "update_playlist_rooms",  # zoom_rooms:write:digital_signage_library_playlists:admin  (admin-level only)
        "update_room_tag",  # zoom_rooms:update:tag:admin  (admin-level only)
        "update_rooms_account_profile",  # zoom_rooms:update:account_profile:admin  (admin-level only)
        "update_rooms_account_settings",  # zoom_rooms:update:account_settings:admin  (admin-level only)
        "update_rooms_location_profile",  # zoom_rooms:update:location:admin  (admin-level only)
        "update_rooms_location_settings",  # zoom_rooms:update:location_settings:admin  (admin-level only)
        "update_rooms_location_structure",  # zoom_rooms:update:location_hierarchy:admin  (admin-level only)
        "update_zoom_room_device_app_version",  # endpoint absent from Zoom's published spec
        "update_zoom_room_profile",  # zoom_rooms:update:room:admin  (admin-level only)
        "update_zoom_room_settings",  # zoom_rooms:update:room_settings:admin  (admin-level only)

        # Revenue Accelerator (49) — MISSING SCOPES, in zra:*. Not one of the scopes
        # named below is in ZOOM_OAUTH_SCOPES, so every operation here fails with an
        # invalid-scope error. The scope shown is the user-level granular scope Zoom
        # publishes for that endpoint unless noted otherwise.
        "zra_add_comment",  # zra:read:list_conversation_comments
        "zra_add_conversation",  # zra:write:conversation
        "zra_assign_team_managers",  # zra:write:team_manages:admin  (admin-level only)
        "zra_assign_team_members",  # zra:write:team_members:admin  (admin-level only)
        "zra_create_team",  # zra:write:team:admin  (admin-level only)
        "zra_delete_comment",  # zra:delete:conversation_comment
        "zra_delete_conversation",  # zra:delete:conversations
        "zra_delete_deal_activity",  # zra:delete:deal_activity
        "zra_delete_team",  # zra:delete:team:admin  (admin-level only)
        "zra_edit_comment",  # zra:update:conversation_comment
        "zra_get_content_analysis",  # zra:read:conversation_analysis
        "zra_get_conversation",  # zra:read:conversations
        "zra_get_crm_settings",  # zra:read:crm_registration:admin  (admin-level only)
        "zra_get_crm_task",  # zra:read:crm_task:admin  (admin-level only)
        "zra_get_deal",  # zra:read:deal
        "zra_get_deal_activities",  # zra:read:list_deal_activities
        "zra_get_indicators",  # zra:read:indicator
        "zra_get_interactions",  # zra:read:conversation_participants
        "zra_get_scorecards",  # zra:read:conversation_scorecards
        "zra_get_team",  # zra:read:team:admin  (admin-level only)
        "zra_grant_access_from",  # zra:write:team:admin  (admin-level only)
        "zra_grant_access_to",  # zra:write:team:admin  (admin-level only)
        "zra_import_crm_accounts",  # zra:write:crm_accounts:admin  (admin-level only)
        "zra_import_crm_contacts",  # zra:write:crm_contact:admin  (admin-level only)
        "zra_import_crm_deals",  # zra:write:crm_deal:admin  (admin-level only)
        "zra_import_crm_leads",  # zra:write:crm_lead:admin  (admin-level only)
        "zra_list_comments",  # zra:read:list_conversation_comments
        "zra_list_conversations",  # zra:read:list_conversations
        "zra_list_crm_accounts",  # zra:read:crm_account:admin  (admin-level only)
        "zra_list_crm_contacts",  # zra:read:crm_contact:admin  (admin-level only)
        "zra_list_crm_deals",  # zra:read:crm_deal:admin  (admin-level only)
        "zra_list_crm_leads",  # zra:read:crm_lead:admin  (admin-level only)
        "zra_list_deal_activities",  # zra:read:list_deal_activities
        "zra_list_deals",  # zra:read:list_deals
        "zra_list_scheduled",  # zra:read:list_conversations
        "zra_list_team_managers",  # zra:read:team_managers
        "zra_list_team_members",  # zra:read:team_members
        "zra_list_teams",  # zra:read:team_list
        "zra_list_unassigned_team_users",  # zra:read:unassigned_team_users:admin  (admin-level only)
        "zra_move_team",  # zra:update:team:admin  (admin-level only)
        "zra_register_crm",  # zra:write:crm_registration:admin  (admin-level only)
        "zra_remove_access_from",  # zra:delete:team:admin  (admin-level only)
        "zra_remove_access_to",  # zra:delete:team:admin  (admin-level only)
        "zra_unassign_team_managers",  # zra:delete:team_managers:admin  (admin-level only)
        "zra_unassign_team_members",  # zra:delete:team_members:admin  (admin-level only)
        "zra_unregister_crm",  # zra:delete:crm_registration:admin  (admin-level only)
        "zra_update_host",  # zra:update:conversation_host
        "zra_update_team",  # zra:update:team:admin  (admin-level only)
        "zra_upload_file",  # zra:write:file

        # Video SDK (34) — no OAuth scope published. Zoom documents these endpoints with
        # no scope requirement at all; they authenticate with their own product
        # credentials rather than a Zoom OAuth scope. Left unmapped because there is
        # nothing to map, not because it is unknown.
        "videosdk_create_session",  # no scope listed by Zoom for this endpoint
        "videosdk_create_storage_location",  # no scope listed by Zoom for this endpoint
        "videosdk_delete_recording_file",  # no scope listed by Zoom for this endpoint
        "videosdk_delete_session",  # no scope listed by Zoom for this endpoint
        "videosdk_delete_session_recordings",  # no scope listed by Zoom for this endpoint
        "videosdk_delete_storage_location",  # no scope listed by Zoom for this endpoint
        "videosdk_get_livestream",  # no scope listed by Zoom for this endpoint
        "videosdk_get_session",  # no scope listed by Zoom for this endpoint
        "videosdk_get_session_recordings",  # no scope listed by Zoom for this endpoint
        "videosdk_get_session_sharing",  # no scope listed by Zoom for this endpoint
        "videosdk_get_session_user_qos",  # no scope listed by Zoom for this endpoint
        "videosdk_get_sip_uri",  # no scope listed by Zoom for this endpoint
        "videosdk_get_storage_location",  # no scope listed by Zoom for this endpoint
        "videosdk_in_session_events",  # no scope listed by Zoom for this endpoint
        "videosdk_list_recordings",  # no scope listed by Zoom for this endpoint
        "videosdk_list_session_recordings",  # no scope listed by Zoom for this endpoint
        "videosdk_list_session_users",  # no scope listed by Zoom for this endpoint
        "videosdk_list_session_users_qos",  # no scope listed by Zoom for this endpoint
        "videosdk_list_sessions",  # no scope listed by Zoom for this endpoint
        "videosdk_list_storage_locations",  # no scope listed by Zoom for this endpoint
        "videosdk_list_stream_ingestions",  # no scope listed by Zoom for this endpoint
        "videosdk_recover_recording_file",  # no scope listed by Zoom for this endpoint
        "videosdk_recover_session_recordings",  # no scope listed by Zoom for this endpoint
        "videosdk_report_cloud_recording",  # no scope listed by Zoom for this endpoint
        "videosdk_report_daily",  # no scope listed by Zoom for this endpoint
        "videosdk_report_operation_logs",  # no scope listed by Zoom for this endpoint
        "videosdk_report_telephone",  # no scope listed by Zoom for this endpoint
        "videosdk_report_webhook_logs",  # no scope listed by Zoom for this endpoint
        "videosdk_switch_storage",  # no scope listed by Zoom for this endpoint
        "videosdk_update_livestream",  # no scope listed by Zoom for this endpoint
        "videosdk_update_livestream_status",  # no scope listed by Zoom for this endpoint
        "videosdk_update_rtms_status",  # no scope listed by Zoom for this endpoint
        "videosdk_update_session_status",  # no scope listed by Zoom for this endpoint
        "videosdk_update_storage_location",  # no scope listed by Zoom for this endpoint

        # Commerce (33) — MISSING SCOPES, in zoom_commerce:*. Not one of the scopes
        # named below is in ZOOM_OAUTH_SCOPES, so every operation here fails with an
        # invalid-scope error. The scope shown is the user-level granular scope Zoom
        # publishes for that endpoint unless noted otherwise.
        "commerce_add_account_contacts",  # zoom_commerce:update:account:admin  (admin-level only)
        "commerce_create_account",  # zoom_commerce:write:sub_account:admin  (admin-level only)
        "commerce_create_deal_registration",  # zoom_commerce:write:deal_registration:admin  (admin-level only)
        "commerce_create_order",  # zoom_commerce:write:order:admin  (admin-level only)
        "commerce_create_quote",  # zoom_commerce:write:quote:admin  (admin-level only)
        "commerce_download_billing_document",  # zoom_commerce:read:billing_documents:admin  (admin-level only)
        "commerce_download_file",  # zoom_commerce:read:file:admin  (admin-level only)
        "commerce_download_pricebook",  # zoom_commerce:read:product_catalog:admin  (admin-level only)
        "commerce_fulfill_quote",  # zoom_commerce:write:quote:admin  (admin-level only)
        "commerce_get_account",  # zoom_commerce:read:account:admin  (admin-level only)
        "commerce_get_catalog",  # zoom_commerce:read:product_catalog:admin  (admin-level only)
        "commerce_get_deal_registration",  # zoom_commerce:read:deal_registration:admin  (admin-level only)
        "commerce_get_file_details",  # zoom_commerce:read:file:admin  (admin-level only)
        "commerce_get_invoice",  # zoom_commerce:read:billing_documents:admin  (admin-level only)
        "commerce_get_offer",  # zoom_commerce:read:product_catalog:admin  (admin-level only)
        "commerce_get_order",  # zoom_commerce:read:order:admin  (admin-level only)
        "commerce_get_quote",  # zoom_commerce:read:quote:admin  (admin-level only)
        "commerce_get_subscription",  # zoom_commerce:read:subscription:admin  (admin-level only)
        "commerce_get_subscription_versions",  # zoom_commerce:read:subscription:admin  (admin-level only)
        "commerce_get_trial",  # zoom_commerce:read:subscription:admin  (admin-level only)
        "commerce_list_accounts",  # zoom_commerce:read:account:admin  (admin-level only)
        "commerce_list_billing_documents",  # zoom_commerce:read:billing_documents:admin  (admin-level only)
        "commerce_list_campaigns",  # zoom_commerce:read:deal_registration:admin  (admin-level only)
        "commerce_list_deal_registrations",  # zoom_commerce:read:deal_registration:admin  (admin-level only)
        "commerce_list_orders",  # zoom_commerce:read:order:admin  (admin-level only)
        "commerce_list_quotes",  # zoom_commerce:read:quote:admin  (admin-level only)
        "commerce_list_subscriptions",  # zoom_commerce:read:subscription:admin  (admin-level only)
        "commerce_list_trials",  # zoom_commerce:read:subscription:admin  (admin-level only)
        "commerce_preview_order",  # zoom_commerce:write:order:admin  (admin-level only)
        "commerce_preview_quote",  # zoom_commerce:write:quote:admin  (admin-level only)
        "commerce_update_deal_registration",  # zoom_commerce:write:deal_registration:admin  (admin-level only)
        "commerce_update_quote",  # zoom_commerce:write:quote:admin  (admin-level only)
        "commerce_upload_file",  # zoom_commerce:write:file:admin  (admin-level only)

        # Quality Management (33) — MISSING SCOPES, in zva:*, scim2:*,
        # zoom_quality_management:*, imchat:*. Not one of the scopes named below is in
        # ZOOM_OAUTH_SCOPES, so every operation here fails with an invalid-scope error.
        # The scope shown is the user-level granular scope Zoom publishes for that
        # endpoint unless noted otherwise.
        "chatbot_delete_message",  # imchat:bot  (classic scope; no granular equivalent published)
        "chatbot_edit_message",  # imchat:bot  (classic scope; no granular equivalent published)
        "chatbot_send_message",  # imchat:bot  (classic scope; no granular equivalent published)
        "qm_add_interaction",  # zoom_quality_management:write:interactions
        "qm_get_evaluation",  # zoom_quality_management:read:evaluations
        "qm_get_interaction",  # zoom_quality_management:read:interactions
        "qm_list_automated_evaluations",  # zoom_quality_management:read:evaluations
        "qm_list_interactions",  # zoom_quality_management:read:interactions
        "qm_list_manual_evaluations",  # zoom_quality_management:read:evaluations
        "scim_create_group",  # scim2:admin  (admin-level only)
        "scim_create_user",  # scim2:admin  (admin-level only)
        "scim_delete_group",  # scim2:admin  (admin-level only)
        "scim_delete_user",  # scim2:admin  (admin-level only)
        "scim_get_group",  # scim2:admin  (admin-level only)
        "scim_get_user",  # scim2:admin  (admin-level only)
        "scim_list_groups",  # scim2:admin  (admin-level only)
        "scim_list_users",  # scim2:admin  (admin-level only)
        "scim_patch_group",  # scim2:admin  (admin-level only)
        "scim_patch_user",  # scim2:admin  (admin-level only)
        "scim_update_group",  # endpoint absent from Zoom's published spec
        "scim_update_user",  # scim2:admin  (admin-level only)
        "va_create_article",  # zva:write:km_article
        "va_delete_article",  # zva:delete:km_article
        "va_get_article",  # zva:read:km_article
        "va_get_sync_status",  # zva:read:km_kb:admin  (admin-level only)
        "va_list_articles",  # zva:read:list_km_articles
        "va_report_engagement_details",  # zva:read:list_queries:admin  (admin-level only)
        "va_report_engagement_variables",  # zva:read:list_variables:admin  (admin-level only)
        "va_report_engagements",  # zva:read:list_engagements:admin  (admin-level only)
        "va_report_surveys",  # zva:read:list_surveys:admin  (admin-level only)
        "va_report_transcripts",  # zva:read:list_transcripts:admin  (admin-level only)
        "va_sync_kb",  # zva:update:km_kb:admin  (admin-level only)
        "va_update_article",  # zva:update:km_article

        # Whiteboard (32) — MISSING SCOPES, in whiteboard:*. Not one of the scopes named
        # below is in ZOOM_OAUTH_SCOPES, so every operation here fails with an invalid-
        # scope error. The scope shown is the user-level granular scope Zoom publishes
        # for that endpoint unless noted otherwise.
        "create_whiteboard",  # whiteboard:write:whiteboard
        "create_whiteboard_export",  # whiteboard:write:export
        "create_whiteboard_project",  # whiteboard:write:project
        "delete_whiteboard",  # whiteboard:delete:whiteboard
        "delete_whiteboard_project",  # whiteboard:delete:project
        "download_whiteboard_activity_file",  # whiteboard:read:archived_file
        "download_whiteboard_export",  # whiteboard:read:export
        "download_whiteboard_file",  # whiteboard:read:file
        "get_project_collaborators",  # whiteboard:read:project_collaborator
        "get_whiteboard",  # whiteboard:read:whiteboard
        "get_whiteboard_collaborators",  # whiteboard:read:list_collaborators
        "get_whiteboard_export_status",  # whiteboard:read:export
        "get_whiteboard_import_status",  # whiteboard:read:import
        "get_whiteboard_project",  # whiteboard:read:project
        "import_whiteboard",  # whiteboard:write:import
        "list_whiteboard_projects",  # whiteboard:read:list_projects
        "list_whiteboard_session_activities",  # whiteboard:read:session
        "list_whiteboard_sessions",  # whiteboard:read:list_sessions
        "list_whiteboard_subprojects",  # whiteboard:read:subproject
        "list_whiteboards",  # whiteboard:read:list_whiteboards
        "move_whiteboards_to_project",  # whiteboard:write:project_whiteboard
        "remove_project_collaborator",  # whiteboard:delete:project_collaborator
        "remove_whiteboard_collaborator",  # whiteboard:delete:collaborator
        "remove_whiteboards_from_project",  # whiteboard:delete:project_whiteboard
        "share_whiteboard",  # whiteboard:write:collaborator
        "share_whiteboard_project",  # whiteboard:write:project_collaborator
        "update_project_collaborators",  # whiteboard:update:project_collaborator
        "update_whiteboard",  # whiteboard:update:whiteboard:admin  (admin-level only)
        "update_whiteboard_collaborators",  # whiteboard:update:collaborator
        "update_whiteboard_project",  # whiteboard:update:project
        "update_whiteboard_share_setting",  # whiteboard:update:share_setting
        "upload_whiteboard_file",  # whiteboard:write:file

        # Zoom Mail (31) — MISSING SCOPES, in email:*. Not one of the scopes named below
        # is in ZOOM_OAUTH_SCOPES, so every operation here fails with an invalid-scope
        # error. The scope shown is the user-level granular scope Zoom publishes for
        # that endpoint unless noted otherwise.
        "mail_batch_delete_messages",  # email:write:batch_delete_msgs
        "mail_batch_modify_messages",  # email:write:batch_modify_msgs
        "mail_create_draft",  # email:write:draft
        "mail_create_label",  # email:write:label
        "mail_delete_draft",  # email:delete:draft
        "mail_delete_label",  # email:delete:label
        "mail_delete_message",  # email:delete:msg
        "mail_delete_thread",  # email:delete:thread
        "mail_get_attachment",  # email:read:attachment
        "mail_get_draft",  # email:read:draft
        "mail_get_label",  # email:read:label
        "mail_get_mailbox_profile",  # email:read:profile
        "mail_get_message",  # email:read:msg
        "mail_get_thread",  # email:read:thread
        "mail_insert_message",  # email:write:msg
        "mail_list_drafts",  # email:read:list_drafts
        "mail_list_history",  # email:read:history
        "mail_list_labels",  # email:read:list_labels
        "mail_list_messages",  # email:read:list_msgs
        "mail_list_threads",  # email:read:list_threads
        "mail_modify_message",  # email:write:modify_msg
        "mail_modify_thread",  # email:write:thread
        "mail_patch_label",  # email:update:label
        "mail_send_draft",  # email:write:send_draft
        "mail_send_message",  # email:write:send_msg
        "mail_trash_message",  # email:write:trash_msg
        "mail_trash_thread",  # email:write:trash_thread
        "mail_untrash_message",  # email:write:untrash_msg
        "mail_untrash_thread",  # email:write:untrash_thread
        "mail_update_draft",  # email:update:draft
        "mail_update_label",  # email:update:label

        # Marketplace (30) — MISSING SCOPES, in marketplace:*, marketplace_app:*, app:*.
        # Not one of the scopes named below is in ZOOM_OAUTH_SCOPES, so every operation
        # here fails with an invalid-scope error. The scope shown is the user-level
        # granular scope Zoom publishes for that endpoint unless noted otherwise.
        "marketplace_add_app_requests",  # marketplace:write:app_request:admin  (admin-level only)
        "marketplace_create_app",  # marketplace:write:app
        "marketplace_create_app_deeplink",  # marketplace:write:app_deeplink:admin  (admin-level only)
        "marketplace_create_event_subscription",  # no scope listed by Zoom for this endpoint
        "marketplace_create_zoomapp_deeplink",  # app:deeplink:write  (classic scope; no granular equivalent published)
        "marketplace_deauthorize",  # endpoint absent from Zoom's published spec
        "marketplace_delete_app",  # marketplace:write:app
        "marketplace_delete_event_subscription",  # no scope listed by Zoom for this endpoint
        "marketplace_export_manifest",  # marketplace:read:app
        "marketplace_generate_deeplink",  # marketplace:write:app_deeplink:admin  (admin-level only)
        "marketplace_get_api_call_logs",  # marketplace:read:list_api_logs:admin  (admin-level only)
        "marketplace_get_app",  # marketplace:read:app
        "marketplace_get_app_requests",  # marketplace:read:app_request:admin  (admin-level only)
        "marketplace_get_monetization_entitlements",  # marketplace:read:list_user_entitlements
        "marketplace_get_user_apps",  # marketplace:read:list_user_app_requests
        "marketplace_get_user_entitlements",  # marketplace:read:list_user_entitlements
        "marketplace_get_webhook_logs",  # marketplace_app:read  (classic scope; no granular equivalent published)
        "marketplace_list_api_call_logs",  # marketplace:read:list_api_logs:admin  (admin-level only)
        "marketplace_list_apps",  # marketplace:read:list_apps:admin  (admin-level only)
        "marketplace_list_event_subscriptions",  # no scope listed by Zoom for this endpoint
        "marketplace_list_webhook_logs",  # marketplace_app:read  (classic scope; no granular equivalent published)
        "marketplace_pre_approve_app",  # marketplace:write:app_pre_approve:admin  (admin-level only)
        "marketplace_rotate_client_secret",  # marketplace:update:client_secret
        "marketplace_subscribe_event_subscription",  # no scope listed by Zoom for this endpoint
        "marketplace_unsubscribe_event_subscription",  # no scope listed by Zoom for this endpoint
        "marketplace_update_app_manifest",  # marketplace:write:app
        "marketplace_update_app_requests",  # marketplace:update:app_request:admin  (admin-level only)
        "marketplace_update_event_subscription",  # no scope listed by Zoom for this endpoint
        "marketplace_update_user_app_subscription",  # marketplace:write:app:admin  (admin-level only)
        "marketplace_validate_manifest",  # marketplace:read:app

        # Number Management (28) — MISSING SCOPES, in number_management:*, phone:*. Not
        # one of the scopes named below is in ZOOM_OAUTH_SCOPES, so every operation here
        # fails with an invalid-scope error. The scope shown is the user-level granular
        # scope Zoom publishes for that endpoint unless noted otherwise.
        "num_add_byoc_numbers",  # number_management:write:byoc_numbers:admin  (admin-level only)
        "num_add_peering_numbers",  # number_management:write:peering_number:admin  (admin-level only)
        "num_allocate_numbers",  # number_management:write:numbers:admin  (admin-level only)
        "num_assign_calling_plan",  # phone:write:calling_plan
        "num_assign_campaign_numbers",  # number_management:update:numbers:admin  (admin-level only)
        "num_assign_numbers_to_user",  # phone:write:user_number
        "num_create_sms_consent",  # number_management:write:sms_consent:admin  (admin-level only)
        "num_delete_numbers",  # number_management:delete:numbers:admin  (admin-level only)
        "num_delete_sms_consent",  # number_management:delete:sms_consent:admin  (admin-level only)
        "num_get_number",  # number_management:read:numbers:admin  (admin-level only)
        "num_get_phone_number",  # phone:read:numbers:admin  (admin-level only)
        "num_get_sms_campaign",  # number_management:read:sms_campaign:admin  (admin-level only)
        "num_get_sms_consent",  # number_management:read:sms_consent:admin  (admin-level only)
        "num_list_carrier_peering_numbers",  # number_management:read:list_carrier_peering_numbers:admin  (admin-level only)
        "num_list_numbers",  # number_management:read:list_numbers:admin  (admin-level only)
        "num_list_peering_numbers",  # number_management:read:list_peering_numbers:admin  (admin-level only)
        "num_list_phone_numbers",  # phone:read:list_numbers:admin  (admin-level only)
        "num_list_plan",  # number_management:read:numbers_plan:admin  (admin-level only)
        "num_list_sms_campaigns",  # number_management:read:list_sms_campaigns:admin  (admin-level only)
        "num_list_sms_consent",  # number_management:read:sms_consent:admin  (admin-level only)
        "num_remove_peering_numbers",  # number_management:delete:peering_number:admin  (admin-level only)
        "num_unassign_calling_plan",  # phone:delete:users_calling_plan
        "num_unassign_campaign_numbers",  # number_management:update:numbers:admin  (admin-level only)
        "num_unassign_number_from_user",  # phone:delete:user_number
        "num_update_number",  # number_management:update:numbers:admin  (admin-level only)
        "num_update_peering_numbers",  # number_management:update:peering_number:admin  (admin-level only)
        "num_update_phone_number_site",  # phone:update:number:admin  (admin-level only)
        "num_update_sms_consent",  # number_management:update:sms_consent:admin  (admin-level only)

        # Zoom Calendar (27) — MISSING SCOPES, in calendar:*. Not one of the scopes
        # named below is in ZOOM_OAUTH_SCOPES, so every operation here fails with an
        # invalid-scope error. The scope shown is the user-level granular scope Zoom
        # publishes for that endpoint unless noted otherwise.
        "calendar_create_calendar",  # calendar:write:calendar
        "calendar_create_event",  # calendar:write:event
        "calendar_delete_acl",  # calendar:delete:acl
        "calendar_delete_calendar",  # calendar:delete:calendar
        "calendar_delete_calendar_list",  # calendar:delete:calendar_list
        "calendar_delete_event",  # calendar:delete:event
        "calendar_get_acl",  # calendar:read:acl
        "calendar_get_calendar",  # calendar:read:calendar
        "calendar_get_calendar_list",  # calendar:read:calendar_list
        "calendar_get_colors",  # calendar:read:color
        "calendar_get_event",  # calendar:read:event
        "calendar_import_event",  # calendar:write:import_event
        "calendar_insert_acl",  # calendar:write:acl
        "calendar_insert_calendar_list",  # calendar:write:calendar_list
        "calendar_list_acl",  # calendar:read:list_acl
        "calendar_list_calendar_list",  # calendar:read:list_calendar_lists
        "calendar_list_event_instances",  # calendar:read:instance_event
        "calendar_list_events",  # calendar:read:list_events
        "calendar_move_event",  # calendar:write:move_event
        "calendar_patch_event",  # calendar:update:event
        "calendar_quick_add_event",  # calendar:write:quick_add_event
        "calendar_stop_watch",  # endpoint absent from Zoom's published spec
        "calendar_update_acl",  # calendar:update:acl
        "calendar_update_calendar",  # calendar:update:calendar
        "calendar_update_calendar_list",  # calendar:update:calendar_list
        "calendar_update_event",  # endpoint absent from Zoom's published spec
        "calendar_watch_events",  # endpoint absent from Zoom's published spec

        # Dashboards (26) — MISSING SCOPES, in dashboard:*. Not one of the scopes named
        # below is in ZOOM_OAUTH_SCOPES, so every operation here fails with an invalid-
        # scope error. The scope shown is the user-level granular scope Zoom publishes
        # for that endpoint unless noted otherwise.
        "dashboard_chat_metrics",  # dashboard:read:chat:admin  (admin-level only)
        "dashboard_client_feedback_detail",  # endpoint absent from Zoom's published spec
        "dashboard_client_satisfaction",  # dashboard:read:meeting_survey:admin  (admin-level only)
        "dashboard_crc_port_usage",  # dashboard:read:crc_port_usage:admin  (admin-level only)
        "dashboard_get_client_feedback",  # dashboard:read:meeting_feedback:admin  (admin-level only)
        "dashboard_get_zoom_room",  # dashboard:read:zoomroom:admin  (admin-level only)
        "dashboard_im_metrics",  # endpoint absent from Zoom's published spec
        "dashboard_list_client_feedback",  # dashboard:read:list_meetings_feedback:admin  (admin-level only)
        "dashboard_list_zoom_rooms",  # dashboard:read:list_zoomrooms:admin  (admin-level only)
        "dashboard_top_issue_types_zoom_rooms",  # dashboard:read:issues_zoomroom:admin  (admin-level only)
        "dashboard_top_issue_zoom_rooms",  # dashboard:read:list_zoomrooms:admin  (admin-level only)
        "dashboard_zoom_room_issues",  # dashboard:read:issues_zoomroom:admin  (admin-level only)
        "get_dashboard_meeting",  # dashboard:read:meeting:admin  (admin-level only)
        "get_dashboard_meeting_participant_qos",  # dashboard:read:meeting_participant_qos:admin  (admin-level only)
        "get_dashboard_webinar",  # dashboard:read:webinar:admin  (admin-level only)
        "get_dashboard_webinar_participant_qos",  # dashboard:read:webinar_participant_qos:admin  (admin-level only)
        "list_dashboard_meeting_participants",  # dashboard:read:list_meeting_participants:admin  (admin-level only)
        "list_dashboard_meeting_participants_qos",  # dashboard:read:list_meeting_participants_qos:admin  (admin-level only)
        "list_dashboard_meeting_participants_satisfaction",  # dashboard:read:post_meeting_feedback:admin  (admin-level only)
        "list_dashboard_meeting_participants_sharing",  # dashboard:read:meeting_sharing:admin  (admin-level only)
        "list_dashboard_meetings",  # dashboard:read:list_meetings:admin  (admin-level only)
        "list_dashboard_webinar_participants",  # dashboard:read:list_webinar_participants:admin  (admin-level only)
        "list_dashboard_webinar_participants_qos",  # dashboard:read:list_webinar_participants_qos:admin  (admin-level only)
        "list_dashboard_webinar_participants_satisfaction",  # dashboard:read:post_webinar_feedback:admin  (admin-level only)
        "list_dashboard_webinar_participants_sharing",  # dashboard:read:webinar_sharing:admin  (admin-level only)
        "list_dashboard_webinars",  # dashboard:read:list_webinars:admin  (admin-level only)

        # Reports (24) — MISSING SCOPES, in report:*. Not one of the scopes named below
        # is in ZOOM_OAUTH_SCOPES, so every operation here fails with an invalid-scope
        # error. The scope shown is the user-level granular scope Zoom publishes for
        # that endpoint unless noted otherwise.
        "get_report_activities",  # report:read:user_activities:admin  (admin-level only)
        "get_report_billing",  # report:read:billing:admin  (admin-level only)
        "get_report_billing_invoices",  # report:read:billing_invoice:admin  (admin-level only)
        "get_report_cloud_recording",  # report:read:admin  (classic scope; no granular equivalent published)
        "get_report_daily",  # report:read:admin  (classic scope; no granular equivalent published)
        "get_report_disclaimer",  # report:read:disclaimer:admin  (admin-level only)
        "get_report_history_meetings",  # report:read:list_history_meetings:admin  (admin-level only)
        "get_report_meeting_activities",  # report:read:meeting_activity_log:admin  (admin-level only)
        "get_report_meeting_details",  # report:read:meeting:admin  (admin-level only)
        "get_report_meeting_participants",  # report:read:list_meeting_participants:admin  (admin-level only)
        "get_report_meeting_polls",  # report:read:list_meeting_polls:admin  (admin-level only)
        "get_report_meeting_qa",  # report:read:meeting_qna:admin  (admin-level only)
        "get_report_meeting_survey",  # report:read:meeting_survey:admin  (admin-level only)
        "get_report_operation_logs",  # report:read:operation_logs:admin  (admin-level only)
        "get_report_remote_support",  # report:read:remote_support:admin  (admin-level only)
        "get_report_telephone",  # report:read:telephone:admin  (admin-level only)
        "get_report_upcoming_events",  # report:read:upcoming_meetings_webinars:admin  (admin-level only)
        "get_report_user_meetings",  # report:read:user:admin  (admin-level only)
        "get_report_users",  # report:read:list_users:admin  (admin-level only)
        "get_report_webinar_details",  # report:read:webinar:admin  (admin-level only)
        "get_report_webinar_participants",  # report:read:list_webinar_participants:admin  (admin-level only)
        "get_report_webinar_polls",  # report:read:list_webinar_polls:admin  (admin-level only)
        "get_report_webinar_qa",  # report:read:webinar_qna:admin  (admin-level only)
        "get_report_webinar_survey",  # report:read:webinar_survey:admin  (admin-level only)

        # AI Services (21) — no OAuth scope published. Zoom documents these endpoints
        # with no scope requirement at all; they authenticate with their own product
        # credentials rather than a Zoom OAuth scope. Left unmapped because there is
        # nothing to map, not because it is unknown.
        "ai_cancel_scribe_job",  # no scope listed by Zoom for this endpoint
        "ai_cancel_summarizer_job",  # no scope listed by Zoom for this endpoint
        "ai_cancel_translator_job",  # no scope listed by Zoom for this endpoint
        "ai_get_scribe_job",  # no scope listed by Zoom for this endpoint
        "ai_get_scribe_job_file",  # no scope listed by Zoom for this endpoint
        "ai_get_summarizer_job",  # no scope listed by Zoom for this endpoint
        "ai_get_summarizer_job_file",  # no scope listed by Zoom for this endpoint
        "ai_get_translator_job",  # no scope listed by Zoom for this endpoint
        "ai_get_translator_job_file",  # no scope listed by Zoom for this endpoint
        "ai_list_scribe_job_files",  # no scope listed by Zoom for this endpoint
        "ai_list_scribe_jobs",  # no scope listed by Zoom for this endpoint
        "ai_list_summarizer_job_files",  # no scope listed by Zoom for this endpoint
        "ai_list_summarizer_jobs",  # no scope listed by Zoom for this endpoint
        "ai_list_translator_job_files",  # no scope listed by Zoom for this endpoint
        "ai_list_translator_jobs",  # no scope listed by Zoom for this endpoint
        "ai_submit_scribe_job",  # no scope listed by Zoom for this endpoint
        "ai_submit_summarizer_job",  # no scope listed by Zoom for this endpoint
        "ai_submit_translator_job",  # no scope listed by Zoom for this endpoint
        "ai_summarize",  # no scope listed by Zoom for this endpoint
        "ai_transcribe",  # no scope listed by Zoom for this endpoint
        "ai_translate",  # no scope listed by Zoom for this endpoint

        # Devices (20) — MISSING SCOPES, in h323_device:*, tsp:*. Not one of the scopes
        # named below is in ZOOM_OAUTH_SCOPES, so every operation here fails with an
        # invalid-scope error. The scope shown is the user-level granular scope Zoom
        # publishes for that endpoint unless noted otherwise.
        "add_sip_callout_countries",  # endpoint absent from Zoom's published spec
        "add_sip_internal_numbers",  # endpoint absent from Zoom's published spec
        "assign_sip_trunk_numbers",  # endpoint absent from Zoom's published spec
        "create_h323_device",  # h323_device:write:device:admin  (admin-level only)
        "create_sip_phone",  # endpoint absent from Zoom's published spec
        "delete_all_sip_trunk_numbers",  # endpoint absent from Zoom's published spec
        "delete_h323_device",  # h323_device:delete:device:admin  (admin-level only)
        "delete_sip_callout_country",  # endpoint absent from Zoom's published spec
        "delete_sip_internal_number",  # endpoint absent from Zoom's published spec
        "delete_sip_phone",  # endpoint absent from Zoom's published spec
        "get_tsp",  # tsp:read:tsp:admin  (admin-level only)
        "list_h323_devices",  # h323_device:read:list_devices:admin  (admin-level only)
        "list_sip_callout_countries",  # endpoint absent from Zoom's published spec
        "list_sip_internal_numbers",  # endpoint absent from Zoom's published spec
        "list_sip_phones",  # endpoint absent from Zoom's published spec
        "list_sip_trunk_numbers",  # endpoint absent from Zoom's published spec
        "update_h323_device",  # h323_device:update:device:admin  (admin-level only)
        "update_sip_phone",  # endpoint absent from Zoom's published spec
        "update_sip_trunk_settings",  # endpoint absent from Zoom's published spec
        "update_tsp",  # tsp:update:tsp:admin  (admin-level only)

        # Scheduler (19) — MISSING SCOPES, in scheduler:*. Not one of the scopes named
        # below is in ZOOM_OAUTH_SCOPES, so every operation here fails with an invalid-
        # scope error. The scope shown is the user-level granular scope Zoom publishes
        # for that endpoint unless noted otherwise.
        "create_scheduler_availability",  # scheduler:write:availability
        "create_scheduler_booking",  # scheduler:write:scheduled_event
        "create_scheduler_schedule",  # scheduler:write:insert_schedule
        "delete_scheduled_event",  # scheduler:delete:scheduled_event
        "delete_scheduler_availability",  # scheduler:delete:availability
        "delete_scheduler_schedule",  # scheduler:delete:delete_schedule
        "get_scheduled_event",  # scheduler:read:scheduled_event
        "get_scheduled_event_attendee",  # scheduler:read:scheduled_event_attendee
        "get_scheduler_availability",  # scheduler:read:availability
        "get_scheduler_routing_response",  # scheduler:read:routing
        "get_scheduler_schedule",  # scheduler:read:get_schedule
        "list_scheduled_events",  # scheduler:read:list_scheduled_events
        "list_scheduler_availability",  # scheduler:read:list_availability
        "list_scheduler_routing_responses",  # scheduler:read:routing
        "list_scheduler_schedules",  # scheduler:read:list_schedule
        "scheduler_analytics",  # scheduler:read:analytics
        "update_scheduled_event",  # scheduler:update:scheduled_event
        "update_scheduler_availability",  # scheduler:update:availability
        "update_scheduler_schedule",  # scheduler:update:patch_schedule

        # Accounts (17) — MISSING SCOPES, in account:*, tracking_field:*. Not one of the
        # scopes named below is in ZOOM_OAUTH_SCOPES, so every operation here fails with
        # an invalid-scope error. The scope shown is the user-level granular scope Zoom
        # publishes for that endpoint unless noted otherwise.
        "create_sub_account",  # endpoint absent from Zoom's published spec
        "create_tracking_field",  # tracking_field:write:tracking_field:admin  (admin-level only)
        "delete_tracking_field",  # tracking_field:delete:tracking_field:admin  (admin-level only)
        "disassociate_sub_account",  # endpoint absent from Zoom's published spec
        "get_account_lock_settings",  # account:read:lock_settings:master  (admin-level only)
        "get_account_managed_domains",  # account:read:managed_domains:master  (admin-level only)
        "get_account_settings",  # account:read:settings:admin  (admin-level only)
        "get_account_trusted_domains",  # account:read:trusted_domains:master  (admin-level only)
        "get_sub_account",  # endpoint absent from Zoom's published spec
        "get_tracking_field",  # tracking_field:read:tracking_field:admin  (admin-level only)
        "list_sub_accounts",  # endpoint absent from Zoom's published spec
        "list_tracking_fields",  # tracking_field:read:list_tracking_fields:admin  (admin-level only)
        "update_account_lock_settings",  # account:update:lock_settings:admin  (admin-level only)
        "update_account_options",  # endpoint absent from Zoom's published spec
        "update_account_owner",  # account:update:owner:admin  (admin-level only)
        "update_account_settings",  # account:update:settings:admin  (admin-level only)
        "update_tracking_field",  # tracking_field:update:tracking_field:admin  (admin-level only)

        # Groups (17) — MISSING SCOPES, in group:*. Not one of the scopes named below is
        # in ZOOM_OAUTH_SCOPES, so every operation here fails with an invalid-scope
        # error. The scope shown is the user-level granular scope Zoom publishes for
        # that endpoint unless noted otherwise.
        "add_group_admins",  # group:write:administrator:admin  (admin-level only)
        "add_group_members",  # group:write:member:admin  (admin-level only)
        "create_group",  # group:write:group:admin  (admin-level only)
        "delete_group",  # group:delete:group:admin  (admin-level only)
        "delete_group_admin",  # group:delete:administrator:admin  (admin-level only)
        "delete_group_member",  # group:delete:member:admin  (admin-level only)
        "delete_group_virtual_background",  # group:delete:virtual_background_files:admin  (admin-level only)
        "get_group",  # group:read:group:admin  (admin-level only)
        "get_group_lock_settings",  # group:read:lock_settings:admin  (admin-level only)
        "get_group_settings",  # group:read:settings:admin  (admin-level only)
        "list_group_admins",  # group:read:administrator:admin  (admin-level only)
        "list_group_members",  # group:read:list_members:admin  (admin-level only)
        "list_groups",  # group:read:list_groups:admin  (admin-level only)
        "update_group",  # group:update:group:admin  (admin-level only)
        "update_group_lock_settings",  # group:update:lock_settings:admin  (admin-level only)
        "update_group_settings",  # group:update:settings:admin  (admin-level only)
        "upload_group_virtual_background",  # group:write:virtual_background_files:admin  (admin-level only)

        # Workforce Management (17) — MISSING SCOPES, in workforce_management:*. Not one
        # of the scopes named below is in ZOOM_OAUTH_SCOPES, so every operation here
        # fails with an invalid-scope error. The scope shown is the user-level granular
        # scope Zoom publishes for that endpoint unless noted otherwise.
        "wfm_create_organizational_group",  # workforce_management:write:organizational_groups:admin  (admin-level only)
        "wfm_delete_historical_agent_status",  # workforce_management:delete:agent_status:admin  (admin-level only)
        "wfm_delete_organizational_group",  # workforce_management:delete:organizational_groups:admin  (admin-level only)
        "wfm_get_forecast",  # workforce_management:read:forecasts:admin  (admin-level only)
        "wfm_get_organizational_group",  # workforce_management:read:organizational_groups:admin  (admin-level only)
        "wfm_get_queue_metrics_import",  # workforce_management:read:queue_metrics:admin  (admin-level only)
        "wfm_import_historical_agent_status",  # workforce_management:write:agent_status:admin  (admin-level only)
        "wfm_import_historical_queue_metrics",  # workforce_management:write:queue_metrics:admin  (admin-level only)
        "wfm_list_agent_adherence",  # workforce_management:read:list_adherence_agents:admin  (admin-level only)
        "wfm_list_filter_groups",  # workforce_management:read:list_filter_groups:admin  (admin-level only)
        "wfm_list_forecasts",  # workforce_management:read:forecasts:admin  (admin-level only)
        "wfm_list_organizational_groups",  # workforce_management:read:organizational_groups:admin  (admin-level only)
        "wfm_list_schedule_report_agents",  # workforce_management:read:list_schedule_agents:admin  (admin-level only)
        "wfm_list_scheduled_agents",  # workforce_management:read:list_schedule_agents:admin  (admin-level only)
        "wfm_list_scheduling_groups",  # workforce_management:read:list_scheduling_groups:admin  (admin-level only)
        "wfm_list_users",  # workforce_management:read:list_users:admin  (admin-level only)
        "wfm_update_organizational_group",  # workforce_management:update:organizational_groups:admin  (admin-level only)

        # Zoom Clips (17) — MISSING SCOPES, in clips:*. Not one of the scopes named
        # below is in ZOOM_OAUTH_SCOPES, so every operation here fails with an invalid-
        # scope error. The scope shown is the user-level granular scope Zoom publishes
        # for that endpoint unless noted otherwise.
        "clips_add_collaborators",  # clips:write:collaborators
        "clips_create_chapters",  # clips:write:chapters
        "clips_delete_clip",  # clips:delete:clip
        "clips_delete_comment",  # clips:delete:comment
        "clips_download_clip",  # clips:read:download_clip
        "clips_duplicate_clip",  # clips:write:duplicate
        "clips_get_chapters",  # clips:read:chapters
        "clips_get_clip",  # clips:read:clip
        "clips_get_transfer_status",  # clips:read:transfer_task_status:admin  (admin-level only)
        "clips_list_clips",  # clips:read:list_user_clips
        "clips_list_collaborators",  # clips:read:list_collaborator
        "clips_list_comments",  # clips:read:list_comments
        "clips_multipart_upload_events",  # clips:write  (classic scope; no granular equivalent published)
        "clips_remove_collaborators",  # clips:delete:collaborators
        "clips_transfer_ownership",  # clips:write:transfer_owner:admin  (admin-level only)
        "clips_update_clip",  # clips:update:clip
        "clips_update_share_settings",  # clips:update:share_setting

        # Docs (16) — MISSING SCOPES, in docs:*. Not one of the scopes named below is in
        # ZOOM_OAUTH_SCOPES, so every operation here fails with an invalid-scope error.
        # The scope shown is the user-level granular scope Zoom publishes for that
        # endpoint unless noted otherwise.
        "docs_add_collaborators",  # docs:write:collaborator
        "docs_create_doc",  # docs:write:file
        "docs_create_export",  # docs:write:export
        "docs_create_import",  # docs:write:import
        "docs_delete_file",  # docs:delete:file
        "docs_get_export_status",  # docs:read:export
        "docs_get_file",  # docs:read:file
        "docs_get_general_access",  # docs:read:general_access
        "docs_get_import_status",  # docs:read:import
        "docs_list_children",  # docs:read:list_children
        "docs_list_collaborators",  # docs:read:list_file_collaborators
        "docs_remove_collaborator",  # docs:delete:collaborator
        "docs_update_collaborator",  # docs:update:collaborator
        "docs_update_file",  # docs:update:file
        "docs_update_general_access",  # docs:update:general_access
        "docs_upload_file",  # docs:write:file_uploads

        # Billing (12) — UNVERIFIABLE. None of these endpoints appear in Zoom's
        # published OpenAPI documents, so the scope they require cannot be confirmed.
        # Left unmapped rather than guessed.
        "add_addon_plan",  # endpoint absent from Zoom's published spec
        "create_plan",  # endpoint absent from Zoom's published spec
        "get_billing_info",  # endpoint absent from Zoom's published spec
        "get_invoice",  # endpoint absent from Zoom's published spec
        "get_plan_usage",  # endpoint absent from Zoom's published spec
        "get_plans",  # endpoint absent from Zoom's published spec
        "list_invoices",  # endpoint absent from Zoom's published spec
        "update_addon_plan",  # endpoint absent from Zoom's published spec
        "update_addon_plan_status",  # endpoint absent from Zoom's published spec
        "update_base_plan",  # endpoint absent from Zoom's published spec
        "update_base_plan_status",  # endpoint absent from Zoom's published spec
        "update_billing_info",  # endpoint absent from Zoom's published spec

        # Contacts (12) — MISSING SCOPES, in contact_group:*, team_chat:*, contact:*.
        # Not one of the scopes named below is in ZOOM_OAUTH_SCOPES, so every operation
        # here fails with an invalid-scope error. The scope shown is the user-level
        # granular scope Zoom publishes for that endpoint unless noted otherwise.
        "add_contact_group_members",  # contact_group:write:admin  (classic scope; no granular equivalent published)
        "create_contact_group",  # contact_group:write:admin  (classic scope; no granular equivalent published)
        "delete_contact_group",  # contact_group:write:admin  (classic scope; no granular equivalent published)
        "get_company_contact",  # team_chat:read:contact
        "get_contact_group",  # contact_group:write:admin  (classic scope; no granular equivalent published)
        "get_user_contact",  # team_chat:read:contact
        "list_contact_group_members",  # contact_group:read:admin  (classic scope; no granular equivalent published)
        "list_contact_groups",  # contact_group:read:admin  (classic scope; no granular equivalent published)
        "list_user_contacts",  # team_chat:read:list_contacts
        "remove_contact_group_member",  # contact_group:write:admin  (classic scope; no granular equivalent published)
        "search_company_contacts",  # contact:read:list_contacts
        "update_contact_group",  # contact_group:write:admin  (classic scope; no granular equivalent published)

        # IM Groups (8) — MISSING SCOPES, in contact_group:*. Not one of the scopes
        # named below is in ZOOM_OAUTH_SCOPES, so every operation here fails with an
        # invalid-scope error. The scope shown is the user-level granular scope Zoom
        # publishes for that endpoint unless noted otherwise.
        "add_im_group_members",  # contact_group:write:member:admin  (admin-level only)
        "create_im_group",  # contact_group:write:group:admin  (admin-level only)
        "delete_im_group",  # contact_group:delete:group:admin  (admin-level only)
        "delete_im_group_member",  # contact_group:delete:member:admin  (admin-level only)
        "get_im_group",  # contact_group:read:group:admin  (admin-level only)
        "list_im_group_members",  # contact_group:read:list_members:admin  (admin-level only)
        "list_im_groups",  # contact_group:read:list_groups:admin  (admin-level only)
        "update_im_group",  # contact_group:update:group:admin  (admin-level only)

        # Roles (8) — MISSING SCOPES, in role:*. Not one of the scopes named below is in
        # ZOOM_OAUTH_SCOPES, so every operation here fails with an invalid-scope error.
        # The scope shown is the user-level granular scope Zoom publishes for that
        # endpoint unless noted otherwise.
        "assign_role_members",  # role:write:member
        "create_role",  # role:write:role
        "delete_role",  # role:delete:role
        "get_role",  # role:read:role
        "list_role_members",  # role:read:list_members
        "list_roles",  # role:read:list_roles
        "unassign_role_member",  # role:delete:member
        "update_role",  # role:update:role

        # Phone (1) — MISSING SCOPES, in phone:*. Not one of the scopes named below is
        # in ZOOM_OAUTH_SCOPES, so every operation here fails with an invalid-scope
        # error. The scope shown is the user-level granular scope Zoom publishes for
        # that endpoint unless noted otherwise.
        "list_call_logs",  # phone:read:list_call_logs:admin  (admin-level only)
    ),
)
