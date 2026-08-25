"""Cloudflare operation → OAuth scope requirements.

Cloudflare's OAuth scopes are its API-token **permission groups** wearing slug
names: "Create your OAuth client" states that scope names correspond to API
token permission names, so ``dns.write`` is the "DNS Write" group,
``workers-kv-storage.read`` is "Workers KV Storage Read", and so on. Meanings
come from the published permission list
(https://developers.cloudflare.com/fundamentals/api/reference/permissions/).
A handful of slugs are internal aliases for a product's older name —
``argotunnel.*`` is Cloudflare Tunnel, ``teams*.*`` is Zero Trust, ``page.*``
is Cloudflare Pages (Page **Rules** and Page **Shield** have their own slugs).

Three structural facts drive the shape here:

- **Scope is per resource family, not per verb-on-resource.** Every family
  splits read/write on the same line Cloudflare draws for its token groups, so
  the table is written as ``(scopes, operations)`` families rather than 449
  individual entries.
- **Not every family has a documented permission group.** Spectrum, Web
  Analytics (RUM), Observatory/Speed, Secondary DNS, Durable Objects and
  account Audit Logs appear in neither the permission reference nor the node's
  requested scope list. Those operations sit in ``unmapped`` with the reason,
  because a guessed slug would be worse than an admitted gap.
- **The node is not OAuth-only.** API Token and Global API Key credentials
  carry no OAuth scopes; a scoped API Token expresses the same permission
  groups by name, so this table doubles as the list of permissions a token
  needs — but only the OAuth credential is checked against it.
"""

from __future__ import annotations

from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement

# (scopes, operations) — one entry per resource family. Read and write of the
# same family are separate lines because Cloudflare grants them separately.
_FAMILIES: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    # ── DNS ────────────────────────────────────────────────────────────────
    # "DNS Read/Write — Grants read/write access to DNS." (zone)
    (
        ("dns.read",),
        (
            "list_dns_records",
            "get_dns_record",
            "export_dns_records",
            "get_dnssec",
            "cloudflare_dns_change",
        ),
    ),
    (
        ("dns.write",),
        (
            "create_dns_record",
            "update_dns_record",
            "delete_dns_record",
            "update_dnssec",
        ),
    ),
    # ── Zone ───────────────────────────────────────────────────────────────
    # "Zone Read/Write — Grants access to zone management."
    (("zone.read",), ("list_zones", "get_zone")),
    (
        ("zone.write",),
        ("create_zone", "edit_zone", "delete_zone", "zone_activation_check"),
    ),
    # "Zone Settings Read/Write". Everything under /zones/{id}/settings/*,
    # including the SSL mode, NEL and Cloudflare Fonts toggles.
    (
        ("zone-settings.read",),
        (
            "get_zone_settings",
            "get_zone_settings_all",
            "get_zone_ssl_settings",
            "get_brotli_setting",
            "get_early_hints_setting",
            "get_http3_setting",
            "get_nel_settings",
            "get_fonts_settings",
        ),
    ),
    (
        ("zone-settings.write",),
        (
            "update_zone_setting",
            "update_zone_ssl_settings",
            "update_brotli_setting",
            "update_early_hints_setting",
            "update_http3_setting",
            "update_nel_settings",
            "update_fonts_settings",
        ),
    ),
    # "Analytics Read — Grants read access to analytics." (zone)
    (("analytics.read",), ("get_zone_analytics",)),
    # "Cache Purge — Grants access to purge cache."
    (("cache.purge",), ("purge_zone_cache", "purge_cache_everything")),
    # ── Account ────────────────────────────────────────────────────────────
    # "Account Settings Read/Write — Grants access to Account resources,
    # account membership, and account level features."
    (
        ("account-settings.read",),
        ("list_account_members", "get_account_member", "list_account_roles"),
    ),
    (
        ("account-settings.write",),
        ("add_account_member", "update_account_member", "remove_account_member"),
    ),
    # "Account Analytics Read". The Analytics Engine SQL API documents this
    # exact permission ("Account | Account Analytics | Read").
    (("account-analytics.read",), ("get_account_analytics", "query_analytics_engine")),
    # ── Workers ────────────────────────────────────────────────────────────
    # "Workers Scripts Read/Write". Secrets, versions, deployments and cron
    # triggers are subresources of a script.
    (
        ("workers-scripts.read",),
        (
            "list_workers",
            "get_worker",
            "list_worker_versions",
            "get_worker_version",
            "list_worker_deployments",
            "get_worker_deployment",
            "list_worker_secrets",
            "get_worker_cron_triggers",
            "cloudflare_worker_deployed",
        ),
    ),
    (
        ("workers-scripts.write",),
        (
            "upload_worker_script",
            "delete_worker",
            "upload_worker_version",
            "create_worker_deployment",
            "put_worker_secret",
            "bulk_upsert_worker_secrets",
            "delete_worker_secret",
            "update_worker_cron_triggers",
        ),
    ),
    # "Workers Routes Read/Write".
    (("workers-routes.read",), ("list_worker_routes",)),
    (
        ("workers-routes.write",),
        ("create_worker_route", "update_worker_route", "delete_worker_route"),
    ),
    # "Workers Tail Read — Grants wrangler tail read permissions." Starting and
    # stopping a tail session is how `wrangler tail` reads; there is no write
    # counterpart in Cloudflare's permission set.
    (
        ("workers-tail.read",),
        ("start_worker_tail", "list_worker_tails", "delete_worker_tail"),
    ),
    # ── Workers KV ─────────────────────────────────────────────────────────
    (
        ("workers-kv-storage.read",),
        (
            "list_kv_namespaces",
            "list_kv_keys",
            "read_kv_value",
            "cloudflare_kv_key_updated",
        ),
    ),
    (
        ("workers-kv-storage.write",),
        (
            "create_kv_namespace",
            "delete_kv_namespace",
            "write_kv_value",
            "delete_kv_value",
            "bulk_write_kv_pairs",
        ),
    ),
    # ── D1 ─────────────────────────────────────────────────────────────────
    (
        ("d1.read",),
        ("list_d1_databases", "get_d1_database", "get_d1_database_import_status"),
    ),
    # The query endpoints take arbitrary SQL, so they carry the write scope
    # regardless of the statement sent.
    (
        ("d1.write",),
        (
            "create_d1_database",
            "delete_d1_database",
            "execute_d1_sql_query",
            "execute_d1_raw_query",
            "list_d1_tables",
            "import_d1_data",
            "export_d1_database_as_sql",
            "cloudflare_d1_new_rows",
        ),
    ),
    # ── R2 (bucket management) ─────────────────────────────────────────────
    # "Workers R2 Storage Read/Write".
    (
        ("workers-r2.read",),
        (
            "list_r2_buckets",
            "get_r2_bucket",
            "get_r2_bucket_details",
            "get_r2_bucket_usage_summary",
            "get_r2_cors_policy",
            "get_r2_lifecycle_rules",
            "list_r2_custom_domains",
            "get_r2_managed_domain",
        ),
    ),
    (
        ("workers-r2.write",),
        (
            "create_r2_bucket",
            "delete_r2_bucket",
            "update_r2_bucket",
            "put_r2_cors_policy",
            "delete_r2_cors_policy",
            "put_r2_lifecycle_rules",
            "delete_r2_lifecycle_rules",
            "create_r2_custom_domain",
            "update_r2_custom_domain",
            "delete_r2_custom_domain",
            "update_r2_managed_domain",
        ),
    ),
    # ── Queues ─────────────────────────────────────────────────────────────
    (("queues.read",), ("list_queues", "get_queue", "list_queue_consumers")),
    # Pull and ack mutate queue state (they consume messages), so they need the
    # write group even though they read data out.
    (
        ("queues.write",),
        (
            "create_queue",
            "update_queue",
            "delete_queue",
            "create_queue_consumer",
            "delete_queue_consumer",
            "send_queue_message",
            "pull_queue_messages",
            "acknowledge_queue_messages",
            "cloudflare_queue_message",
            "cloudflare_queue_delivery_event",
            "cloudflare_r2_object_event",
        ),
    ),
    # ── Pages ──────────────────────────────────────────────────────────────
    (
        ("page.read",),
        (
            "list_pages_projects",
            "get_pages_project",
            "list_pages_deployments",
            "get_pages_deployment",
            "cloudflare_pages_deploy",
        ),
    ),
    (
        ("page.write",),
        (
            "create_pages_project",
            "delete_pages_project",
            "delete_pages_deployment",
            "retry_pages_deployment",
        ),
    ),
    # ── Stream ─────────────────────────────────────────────────────────────
    (
        ("stream.read",),
        (
            "list_stream_videos",
            "get_stream_video",
            "get_stream_video_embed_code",
            "list_stream_captions",
            "list_stream_audio_tracks",
            "list_stream_live_inputs",
            "list_stream_signing_keys",
            "list_stream_watermarks",
            "get_stream_watermark",
            "cloudflare_stream_event",
        ),
    ),
    (
        ("stream.write",),
        (
            "create_stream_upload_url",
            "update_stream_video",
            "delete_stream_video",
            "upload_stream_caption",
            "delete_stream_caption",
            "add_stream_audio_track",
            "edit_stream_audio_track",
            "delete_stream_audio_track",
            "create_stream_live_input",
            "delete_stream_live_input",
            "create_stream_signing_key",
            "delete_stream_signing_key",
            "create_stream_signed_url",
            "create_stream_watermark",
            "delete_stream_watermark",
        ),
    ),
    # ── Images ─────────────────────────────────────────────────────────────
    (
        ("images.read",),
        (
            "list_images",
            "get_image",
            "get_image_usage_statistics",
            "list_image_variants",
            "get_image_variant",
            "list_image_signing_keys",
        ),
    ),
    (
        ("images.write",),
        (
            "create_image_direct_upload_url",
            "update_image_metadata",
            "delete_image",
            "create_image_variant",
            "update_image_variant",
            "delete_image_variant",
            "create_image_signing_key",
            "delete_image_signing_key",
        ),
    ),
    # ── Vectorize ──────────────────────────────────────────────────────────
    (
        ("vectorize.read",),
        (
            "list_vectorize_indexes",
            "get_vectorize_index",
            "get_vectorize_index_info",
            "list_vectorize_metadata_indexes",
            "get_vectorize_vectors_by_ids",
            "query_vectorize_index",
        ),
    ),
    (
        ("vectorize.write",),
        (
            "create_vectorize_index",
            "delete_vectorize_index",
            "create_vectorize_metadata_index",
            "delete_vectorize_metadata_index",
            "upsert_vectors_to_index",
            "delete_vectors_from_index",
        ),
    ),
    # ── Pipelines ──────────────────────────────────────────────────────────
    (("pipelines.read",), ("list_pipelines", "get_pipeline")),
    (("pipelines.write",), ("create_pipeline", "update_pipeline", "delete_pipeline")),
    # ── Secrets Store ──────────────────────────────────────────────────────
    (
        ("secrets-store.read",),
        ("list_secrets_stores", "list_store_secrets", "get_store_secret"),
    ),
    (
        ("secrets-store.write",),
        (
            "create_secrets_store",
            "delete_secrets_store",
            "create_store_secret",
            "update_store_secret",
            "delete_store_secret",
        ),
    ),
    # ── Workers AI ─────────────────────────────────────────────────────────
    # The REST API guide states a token "will need permissions for both
    # `Workers AI - Read` and `Workers AI - Edit`" to run inference.
    (
        ("ai.read",),
        (
            "list_workers_ai_models",
        ),
    ),
    (
        ("ai.read", "ai.write"),
        (
            "run_workers_ai_inference",
        ),
    ),
    # ── Access (Cloudflare One) ────────────────────────────────────────────
    (
        ("access-app.read",),
        ("list_access_applications", "get_access_application"),
    ),
    (
        ("access-app.write",),
        ("create_access_application", "delete_access_application"),
    ),
    (
        ("access-policy.read",),
        ("list_access_application_policies", "get_access_policy"),
    ),
    (
        ("access-policy.write",),
        ("create_access_policy", "update_access_policy", "delete_access_policy"),
    ),
    (("access-group.read",), ("list_access_groups", "get_access_group")),
    (
        ("access-group.write",),
        ("create_access_group", "update_access_group", "delete_access_group"),
    ),
    (
        ("access-idp.read",),
        ("list_identity_providers", "get_identity_provider"),
    ),
    (
        ("access-idp.write",),
        (
            "create_identity_provider",
            "update_identity_provider",
            "delete_identity_provider",
        ),
    ),
    (("access-service-token.read",), ("list_access_service_tokens",)),
    (
        ("access-service-token.write",),
        (
            "create_access_service_token",
            "refresh_access_service_token",
            "delete_access_service_token",
        ),
    ),
    (
        ("access-users.read",),
        ("list_access_users", "get_access_user", "list_access_user_sessions"),
    ),
    (("access-org.read",), ("get_access_organization",)),
    (("access-org.write",), ("update_access_organization",)),
    # "Access: Organizations Revoke — Grants ability to revoke user sessions."
    (("access-org.revoke",), ("revoke_access_user_session",)),
    # "Access: Keys Edit — Grants ability to rotate Access signing keys."
    (("access-key.write",), ("create_access_key_rotation",)),
    # ── Zero Trust ─────────────────────────────────────────────────────────
    # "Cloudflare One Networks Read/Write — Grants access to Cloudflare One
    # routes and virtual networks."
    (
        ("teams-networks.read",),
        ("list_tunnel_routes", "list_virtual_networks", "get_virtual_network"),
    ),
    (
        ("teams-networks.write",),
        (
            "create_tunnel_route",
            "update_tunnel_route",
            "delete_tunnel_route",
            "create_virtual_network",
            "update_virtual_network",
            "delete_virtual_network",
        ),
    ),
    # "Zero Trust Read/Write — Grants access to Cloudflare Zero Trust
    # resources." Gateway rules, lists, locations and configuration.
    (
        ("teams.read",),
        (
            "get_gateway_configuration",
            "list_gateway_rules",
            "get_gateway_rule",
            "list_gateway_lists",
            "get_gateway_list",
            "list_gateway_list_items",
            "list_gateway_locations",
            "get_gateway_location",
        ),
    ),
    (
        ("teams.write",),
        (
            "update_gateway_configuration",
            "create_gateway_rule",
            "update_gateway_rule",
            "delete_gateway_rule",
            "create_gateway_list",
            "update_gateway_list",
            "delete_gateway_list",
            "create_gateway_location",
            "delete_gateway_location",
        ),
    ),
    # ── Cloudflare Tunnel ──────────────────────────────────────────────────
    # "Cloudflare Tunnel Read/Edit" — slug keeps the Argo Tunnel name.
    (
        ("argotunnel.read",),
        (
            "list_tunnels",
            "get_tunnel",
            "get_tunnel_token",
            "get_tunnel_configuration",
            "list_tunnel_connections",
        ),
    ),
    (
        ("argotunnel.write",),
        ("create_tunnel", "update_tunnel", "delete_tunnel", "put_tunnel_configuration"),
    ),
    # ── Health Checks ──────────────────────────────────────────────────────
    (
        ("healthcheck.read",),
        ("list_health_checks", "get_health_check", "cloudflare_health_check_status"),
    ),
    (
        ("healthcheck.write",),
        ("create_health_check", "update_health_check", "delete_health_check"),
    ),
    # ── Load Balancing ─────────────────────────────────────────────────────
    # "Load Balancers Read/Edit" (zone) vs "Load Balancing: Monitors and Pools
    # Read/Edit" (account) — two separate groups.
    (("load-balancers.read",), ("list_load_balancers", "get_load_balancer")),
    (
        ("load-balancers.write",),
        ("create_load_balancer", "update_load_balancer", "delete_load_balancer"),
    ),
    (
        ("load-balancing-monitors-and-pools.read",),
        (
            "list_load_balancer_monitors",
            "get_load_balancer_monitor",
            "list_load_balancer_pools",
            "get_load_balancer_pool",
            "get_load_balancer_pool_health",
        ),
    ),
    (
        ("load-balancing-monitors-and-pools.write",),
        (
            "create_load_balancer_monitor",
            "delete_load_balancer_monitor",
            "create_load_balancer_pool",
            "update_load_balancer_pool",
            "delete_load_balancer_pool",
        ),
    ),
    # ── Waiting Rooms ──────────────────────────────────────────────────────
    (
        ("waiting-rooms.read",),
        (
            "list_waiting_rooms",
            "get_waiting_room",
            "get_waiting_room_status",
            "list_waiting_room_events",
        ),
    ),
    (
        ("waiting-rooms.write",),
        (
            "create_waiting_room",
            "update_waiting_room",
            "delete_waiting_room",
            "create_waiting_room_event",
        ),
    ),
    # ── Page Shield (client-side security) ─────────────────────────────────
    (
        ("page-shield.read",),
        (
            "get_page_shield_settings",
            "list_page_shield_scripts",
            "get_page_shield_script",
            "list_page_shield_connections",
            "get_page_shield_connection",
            "list_page_shield_policies",
        ),
    ),
    # ── Bot Management ─────────────────────────────────────────────────────
    (
        ("bot-management.read",),
        (
            "get_bot_management",
        ),
    ),
    (
        ("bot-management.write",),
        (
            "update_bot_management",
        ),
    ),
    # ── API Shield / API Gateway (zone) ────────────────────────────────────
    (
        ("api-gateway.read",),
        ("get_api_shield_settings", "list_api_shield_endpoints"),
    ),
    (
        ("api-gateway.write",),
        ("update_api_shield_settings", "create_api_shield_endpoint"),
    ),
    # ── WAF / Firewall ─────────────────────────────────────────────────────
    # "Zone WAF Read/Write" covers the managed WAF packages.
    (
        ("zone-waf.read",),
        (
            "list_zone_waf_packages",
            "get_waf_package",
            "list_waf_package_rule_groups",
            "list_waf_package_rules",
        ),
    ),
    (("zone-waf.write",), ("update_waf_rule",)),
    # "Firewall Services Read/Write — Grants access to Firewall resources."
    # Legacy firewall rules and legacy rate limiting both live under
    # /zones/{id}/firewall and /zones/{id}/rate_limits.
    (
        ("firewall-services.read",),
        ("list_firewall_rules", "list_rate_limits", "get_rate_limit"),
    ),
    (
        ("firewall-services.write",),
        (
            "create_firewall_rule",
            "delete_firewall_rule",
            "create_rate_limit",
            "update_rate_limit",
            "delete_rate_limit",
        ),
    ),
    # ── Rules lists & account rulesets ─────────────────────────────────────
    # "Account Rule Lists Read/Write — Grants access to Account Filter Lists."
    (
        ("account-rule-lists.read",),
        (
            "list_rules_lists",
            "get_rules_list",
            "list_rules_list_items",
            "get_rules_list_operation",
        ),
    ),
    (
        ("account-rule-lists.write",),
        (
            "create_rules_list",
            "update_rules_list",
            "delete_rules_list",
            "create_rules_list_items",
            "replace_rules_list_items",
            "delete_rules_list_items",
        ),
    ),
    # "Account Rulesets Read."
    (("account-rulesets.read",), ("list_account_rulesets", "get_account_ruleset")),
    # ── Page Rules ─────────────────────────────────────────────────────────
    (("page-rules.read",), ("list_page_rules", "get_page_rule")),
    (
        ("page-rules.write",),
        ("create_page_rule", "update_page_rule", "delete_page_rule"),
    ),
    # ── Snippets ───────────────────────────────────────────────────────────
    (("snippets.read",), ("list_snippets", "get_snippet", "list_snippet_rules")),
    (("snippets.write",), ("put_snippet", "delete_snippet")),
    # ── Zaraz ──────────────────────────────────────────────────────────────
    (("zaraz.read",), ("get_zaraz_config",)),
    (("zaraz.write",), ("update_zaraz_config", "publish_zaraz_config")),
    # ── SSL & certificates ─────────────────────────────────────────────────
    # "SSL and Certificates Read/Write — Grants access to SSL configuration and
    # certificate management." Custom hostnames are SSL for SaaS.
    (
        ("ssl-and-certificates.read",),
        ("list_zone_ssl_certificates", "list_custom_hostnames", "get_custom_hostname"),
    ),
    (
        ("ssl-and-certificates.write",),
        (
            "upload_ssl_certificate",
            "delete_ssl_certificate",
            "create_custom_hostname",
            "update_custom_hostname",
            "delete_custom_hostname",
        ),
    ),
    # ── Email Routing ──────────────────────────────────────────────────────
    (
        ("email-routing-rule.read",),
        ("get_email_routing_settings", "list_email_routing_rules"),
    ),
    (
        ("email-routing-rule.write",),
        (
            "create_email_routing_rule",
            "delete_email_routing_rule",
            "enable_email_routing",
            "disable_email_routing",
        ),
    ),
    (
        ("email-routing-address.read",),
        ("list_email_routing_destination_addresses",),
    ),
    (
        ("email-routing-address.write",),
        ("create_email_routing_destination", "delete_email_routing_destination"),
    ),
    # ── Logs ───────────────────────────────────────────────────────────────
    # "Logs Read — read access to logs using Logpull or Instant Logs."
    # "Logs Edit — read and write access to Logpull, Logpush and Instant Logs."
    # Logpush is named only in the Edit group, so even LISTING jobs takes the
    # write scope. Account-scoped jobs use the account group, zone-scoped the
    # zone group.
    (
        ("logs.write",),
        (
            "list_zone_logpush_jobs",
            "create_zone_logpush_job",
            "delete_zone_logpush_job",
        ),
    ),
    (
        ("account-logs.write",),
        (
            "list_account_logpush_jobs",
            "get_logpush_job",
            "create_logpush_job",
            "update_logpush_job",
            "delete_logpush_job",
        ),
    ),
    # ── Notifications / alerting ───────────────────────────────────────────
    # Every webhook trigger registers an alert policy plus a webhook
    # destination, so they need the write group, not just read.
    (
        ("notifications.read",),
        (
            "list_alert_policies",
            "get_alert_policy",
            "list_available_alerts",
            "get_notification_history",
            "list_notification_webhooks",
        ),
    ),
    (
        ("notifications.write",),
        (
            "create_alert_policy",
            "update_alert_policy",
            "delete_alert_policy",
            "create_notification_webhook",
            "update_notification_webhook",
            "delete_notification_webhook",
            "cloudflare_alert",
            "cloudflare_ddos_alert",
            "cloudflare_ssl_alert",
            "cloudflare_tunnel_alert",
            "cloudflare_worker_alert",
            "cloudflare_load_balancer_alert",
            "cloudflare_waiting_room_alert",
            "cloudflare_page_shield_alert",
            "cloudflare_zero_trust_alert",
            "cloudflare_email_routing_alert",
            "cloudflare_magic_transit_alert",
        ),
    ),
    # ── Restored implemented families (Intel, Magic Transit, Calls, Radar,
    #    Addressing/BYOIP, URL Scanner, Bot Management, Workers AI, Analytics
    #    Engine SQL, Log Explorer/Logpull/CMB, R2 Event Notifications) ──
    (
        ('account-analytics.read',),
        (
            'get_analytics_engine_dataset_schema',
            'get_analytics_engine_event_count',
            'list_analytics_engine_datasets',
            'list_analytics_engine_timezones',
            'query_analytics_engine_aggregated',
            'query_analytics_engine_raw',
            'query_analytics_engine_timeseries',
            'query_analytics_engine_top_values',
            'query_analytics_engine_weighted_avg',
        ),
    ),
    (
        ('account-logs.read',),
        (
            'get_cmb_config',
        ),
    ),
    (
        ('account-logs.read', 'logs.read'),
        (
            'get_log_explorer_dataset',
            'list_log_explorer_available_datasets',
            'list_log_explorer_datasets',
            'query_log_explorer_sql',
        ),
    ),
    (
        ('account-logs.write',),
        (
            'delete_cmb_config',
            'update_cmb_config',
        ),
    ),
    (
        ('account-logs.write', 'logs.write'),
        (
            'create_log_explorer_dataset',
            'update_log_explorer_dataset',
        ),
    ),
    (
        ('address-maps.read',),
        (
            'get_address_map',
            'list_address_maps',
        ),
    ),
    (
        ('address-maps.write',),
        (
            'add_ip_to_address_map',
            'add_zone_to_address_map',
            'create_address_map',
            'delete_address_map',
            'remove_ip_from_address_map',
            'remove_zone_from_address_map',
            'update_address_map',
        ),
    ),
    (
        ('ai.read',),
        (
            'get_ai_model_schema',
            'list_ai_authors',
            'list_ai_finetunes',
            'list_ai_tasks',
            'list_public_ai_finetunes',
        ),
    ),
    (
        ('ai.write',),
        (
            'convert_file_to_markdown',
            'create_ai_finetune',
            'run_ai_image_classification',
            'run_ai_object_detection',
            'run_ai_speech_to_text',
            'run_ai_summarization',
            'run_ai_text_embeddings',
            'run_ai_text_generation',
            'run_ai_text_to_image',
            'run_ai_translation',
        ),
    ),
    (
        ('bot-management-feedback.read',),
        (
            'get_bot_management_analytics',
            'list_bot_feedback_reports',
        ),
    ),
    (
        ('bot-management-feedback.write',),
        (
            'submit_bot_feedback',
        ),
    ),
    (
        ('bot-management.read',),
        (
            'get_bot_score_thresholds',
        ),
    ),
    (
        ('bot-management.write',),
        (
            'configure_javascript_detection',
            'update_bot_score_thresholds',
        ),
    ),
    (
        ('calls.read',),
        (
            'get_calls_app',
            'get_calls_turn_key',
            'list_calls_apps',
            'list_calls_turn_keys',
        ),
    ),
    (
        ('calls.write',),
        (
            'create_calls_app',
            'create_calls_turn_key',
            'delete_calls_app',
            'delete_calls_turn_key',
            'update_calls_app',
            'update_calls_turn_key',
        ),
    ),
    (
        ('intel.read',),
        (
            'get_attack_surface_issues_by_severity',
            'get_attack_surface_issues_by_type',
            'get_intel_asn',
            'get_intel_asn_subnets',
            'get_intel_dns',
            'get_intel_domain',
            'get_intel_domain_bulk',
            'get_intel_domain_history',
            'get_intel_indicator_feed',
            'get_intel_indicator_feed_data',
            'get_intel_ip',
            'get_intel_whois',
            'list_attack_surface_issue_types',
            'list_attack_surface_issues',
            'list_intel_feed_permissions',
            'list_intel_indicator_feeds',
            'list_intel_sinkholes',
        ),
    ),
    (
        ('intel.write',),
        (
            'add_intel_feed_permission',
            'create_intel_indicator_feed',
            'create_intel_miscategorization',
            'dismiss_attack_surface_issue',
            'remove_intel_feed_permission',
            'update_intel_indicator_feed',
        ),
    ),
    (
        ('ip-prefix-bgp-on-demand.read',),
        (
            'get_bgp_prefix_advertisement_status',
        ),
    ),
    (
        ('ip-prefix-bgp-on-demand.write',),
        (
            'update_bgp_prefix',
            'update_bgp_prefix_advertisement',
        ),
    ),
    (
        ('ip-prefix.read',),
        (
            'download_loa_document',
            'get_ip_prefix',
            'get_prefix_service_binding',
            'get_regional_hostname',
            'list_addressing_services',
            'list_bgp_prefixes',
            'list_ip_prefixes',
            'list_prefix_delegations',
            'list_prefix_service_bindings',
            'list_regional_hostname_regions',
            'list_regional_hostnames',
        ),
    ),
    (
        ('ip-prefix.write',),
        (
            'create_ip_prefix',
            'create_prefix_delegation',
            'create_prefix_service_binding',
            'create_regional_hostname',
            'delete_ip_prefix',
            'delete_prefix_delegation',
            'delete_prefix_service_binding',
            'delete_regional_hostname',
            'update_ip_prefix',
            'update_regional_hostname',
            'upload_loa_document',
        ),
    ),
    (
        ('logs.read',),
        (
            'get_log_retention_flag',
            'get_logpull_fields',
            'get_logpull_logs',
            'get_logpull_rayid',
        ),
    ),
    (
        ('logs.write',),
        (
            'update_log_retention_flag',
        ),
    ),
    (
        ('magic-transit.read',),
        (
            'get_magic_cf_interconnect',
            'get_magic_gre_tunnel',
            'list_magic_apps',
            'list_magic_cf_interconnects',
            'list_magic_gre_tunnels',
        ),
    ),
    (
        ('magic-transit.write',),
        (
            'create_magic_app',
            'create_magic_gre_tunnel',
            'delete_magic_app',
            'delete_magic_gre_tunnel',
            'update_magic_app',
            'update_magic_cf_interconnect',
            'update_magic_gre_tunnel',
        ),
    ),
    (
        ('queues.read', 'workers-r2.read'),
        (
            'get_r2_event_notification_config',
            'get_r2_event_notification_queue_rules',
        ),
    ),
    (
        ('queues.write', 'workers-r2.write'),
        (
            'delete_r2_event_notification_rules',
            'put_r2_event_notification_rules',
        ),
    ),
    (
        ('radar.read',),
        (
            'get_radar_ai_bots_summary',
            'get_radar_ai_bots_summary_by_crawl_purpose',
            'get_radar_ai_bots_summary_by_industry',
            'get_radar_ai_bots_summary_by_user_agent',
            'get_radar_ai_bots_timeseries',
            'get_radar_ai_bots_timeseries_by_user_agent',
            'get_radar_ai_bots_timeseries_groups',
            'get_radar_ai_inference_summary_by_model',
            'get_radar_ai_inference_summary_by_task',
            'get_radar_ai_inference_timeseries_by_model',
            'get_radar_ai_inference_timeseries_by_task',
        ),
    ),
    (
        ('url-scanner.read',),
        (
            'get_url_scan',
            'get_url_scan_dom',
            'get_url_scan_har',
            'get_url_scan_screenshot',
            'search_url_scans',
        ),
    ),
    (
        ('url-scanner.write',),
        (
            'bulk_submit_url_scans',
            'submit_url_scan',
        ),
    ),
)

_REQUIREMENTS: dict[str, ScopeRequirement] = {
    operation: ScopeRequirement(scopes=scopes)
    for scopes, operations in _FAMILIES
    for operation in operations
}

# Operations with no scope entry, grouped by why. Every one of these is a real
# gap, not a shrug: either Cloudflare publishes no permission group for the
# product, or two candidate slugs fit and the docs do not say which.
_UNMAPPED: tuple[str, ...] = (
    # -- No permission group published, and no matching slug in the node's
    #    requested scope list. These likely CANNOT be authorized over OAuth at
    #    all; see the module report.
    # MISSING SCOPE: spectrum.* — Spectrum has no documented permission group.
    "list_spectrum_apps",
    "get_spectrum_app",
    "create_spectrum_app",
    "update_spectrum_app",
    "delete_spectrum_app",
    # MISSING SCOPE: web-analytics.* / rum.* — RUM site management.
    "list_web_analytics_sites",
    "get_web_analytics_site",
    "get_web_analytics_summary",
    "create_web_analytics_site",
    "delete_web_analytics_site",
    # MISSING SCOPE: speed/observatory — /speed_api has no documented group.
    "list_observatory_pages",
    "list_page_speed_tests",
    "create_page_speed_test",
    "delete_page_speed_tests",
    "get_speed_test_schedule",
    # MISSING SCOPE: audit logs — no account audit-log permission group is
    # published ("Access: Audit Logs Read" is Cloudflare Access only).
    "list_audit_logs",
    "cloudflare_audit_log",
    # MISSING SCOPE: durable objects — no documented group; workers-scripts.*
    # is a guess.
    "list_durable_object_namespaces",
    "list_durable_objects",
    # MISSING SCOPE: page-shield.write — the requested list carries the odd
    # `page.shield` / `domain-page.shield` slugs but no page-shield write
    # scope, so these writes may be unauthorizable.
    "create_page_shield_policy",
    "delete_page_shield_policy",
    "update_page_shield_settings",
    # -- Ambiguous between two requested slugs; docs do not disambiguate. ----
    # aig.* vs agw.* both appear in the requested list for AI Gateway.
    "list_ai_gateways",
    "get_ai_gateway",
    "create_ai_gateway",
    "update_ai_gateway",
    "delete_ai_gateway",
    "list_ai_gateway_logs",
    "get_ai_gateway_log",
    "get_ai_gateway_log_request",
    "get_ai_gateway_log_response",
    "delete_ai_gateway_logs",
    "list_ai_gateway_datasets",
    "create_ai_gateway_dataset",
    "delete_ai_gateway_dataset",
    # Secondary DNS: account-dns-settings.* vs zone-dns-settings.* vs dns.*.
    "get_secondary_dns_config",
    "update_secondary_dns_config",
    "list_secondary_dns_peers",
    "get_secondary_dns_peer",
    "create_secondary_dns_peer",
    "update_secondary_dns_peer",
    "delete_secondary_dns_peer",
    # Argo / Tiered Cache / Cache Reserve sit under /cache and /argo, not
    # /settings: zone-settings.* vs cache-settings.* is undocumented.
    "get_argo_smart_routing",
    "update_argo_smart_routing",
    "get_tiered_caching",
    "update_tiered_caching",
    "get_regional_tiered_cache",
    "update_regional_tiered_cache",
    "get_cache_reserve",
    "update_cache_reserve",
    # Zone rulesets are permissioned per PHASE (transform rules, config
    # settings, custom errors, origin, managed headers, …), so no single slug
    # covers a generic zone-ruleset call.
    "list_zone_rulesets",
    "get_zone_ruleset",
    "get_zone_ruleset_phase",
    "create_zone_ruleset",
    "update_zone_ruleset",
    "delete_zone_ruleset",
    "update_zone_ruleset_phase",
    "create_zone_ruleset_rule",
    "delete_zone_ruleset_rule",
    # R2 object access goes through the S3-compatible API with R2 access keys,
    # which accepts no Cloudflare API token or OAuth scope at all.
    "list_r2_objects",
    "get_r2_object",
    "put_r2_object",
    "delete_r2_object",
    "get_r2_presigned_url",
    "cloudflare_r2_new_object",
    # -- Restored families: ops with no confidently-requested permission slug.

)

CLOUDFLARE_SCOPES = ScopeRegistry(
    provider="cloudflare",
    requirements=_REQUIREMENTS,
    unmapped=_UNMAPPED,
)
