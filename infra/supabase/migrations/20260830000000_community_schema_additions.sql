-- What the community edition needs beyond the reviewed base schema: the tables
-- the export had dropped, and columns the runtime reads. Every statement is
-- idempotent because installs from the 0.1 and 0.2 releases already carry the
-- seven tables complete_community_schema.sql created, and apply this later.
--
-- Was 20260820000001_restore_dropped_tables.sql; renumbered to run after
-- complete_community_schema.sql so every install agrees on which definition
-- of a shared table came first.

-- The tables the curated schema dropped and the code still queries.
--
-- oss/overrides/infra/supabase/migrations/20260812000000_initial_schema.sql is a
-- hand-curated pg_dump, and curation removed twenty tables that shipped backend
-- modules issue SQL against — the shared-run-link repository, the recurring
-- charge sweep, the credential-request routes, the feedback choke point, the
-- skill picker, the template service. A self-hosted install answered
-- "relation ... does not exist" on each of those paths, and nothing noticed
-- because the open edition's CI ran a hand-picked list of test files rather than
-- its suite.
--
-- Generated rather than written: the set is `tables in the hosted schema` minus
-- `tables in this one`, filtered to those a non-test module under backend/ names
-- in a FROM/INTO/UPDATE/JOIN. stripe_webhook_events is the one exclusion — its
-- only writer is the payment webhook route, which does not ship.
--
-- Row-level security comes with them, as it stands in the hosted schema; the
-- coverage test in backend/tests/test_public_schema_rls_coverage.py is what
-- says that is enough.

--
-- PostgreSQL database dump
--

-- Dumped from database version 16.12 (Debian 16.12-1.pgdg12+1)
-- Dumped by pg_dump version 16.12 (Debian 16.12-1.pgdg12+1)


-- The fork feature materialises a workflow's database into per-owner tables here
-- (repositories/share.py), so the schema has to exist even though nothing in the
-- dump lives in it.
CREATE SCHEMA IF NOT EXISTS user_tables;

-- The trigger functions these tables install. `pg_dump -t` carries the
-- triggers but not the functions they call, so a table arrives with a
-- trigger pointing at nothing.
CREATE OR REPLACE FUNCTION public.update_template_vote_counts()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.vote_type = 1 THEN
            UPDATE public.workflow_templates
            SET upvote_count = upvote_count + 1
            WHERE id = NEW.template_id;
        ELSE
            UPDATE public.workflow_templates
            SET downvote_count = downvote_count + 1
            WHERE id = NEW.template_id;
        END IF;
        RETURN NEW;
    ELSIF TG_OP = 'UPDATE' THEN
        -- Handle vote change (e.g., upvote to downvote)
        IF OLD.vote_type != NEW.vote_type THEN
            IF OLD.vote_type = 1 THEN
                UPDATE public.workflow_templates
                SET upvote_count = upvote_count - 1, downvote_count = downvote_count + 1
                WHERE id = NEW.template_id;
            ELSE
                UPDATE public.workflow_templates
                SET upvote_count = upvote_count + 1, downvote_count = downvote_count - 1
                WHERE id = NEW.template_id;
            END IF;
        END IF;
        RETURN NEW;
    ELSIF TG_OP = 'DELETE' THEN
        IF OLD.vote_type = 1 THEN
            UPDATE public.workflow_templates
            SET upvote_count = GREATEST(0, upvote_count - 1)
            WHERE id = OLD.template_id;
        ELSE
            UPDATE public.workflow_templates
            SET downvote_count = GREATEST(0, downvote_count - 1)
            WHERE id = OLD.template_id;
        END IF;
        RETURN OLD;
    END IF;
    RETURN NULL;
END;
$function$
;

CREATE OR REPLACE FUNCTION public.update_template_vote_updated_at()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$function$
;

CREATE OR REPLACE FUNCTION public.update_workflow_embeddings_updated_at()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$function$
;

CREATE OR REPLACE FUNCTION public.update_workflow_template_updated_at()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$function$
;

--
-- Name: agent_email_replies; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE IF NOT EXISTS public.agent_email_replies (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid NOT NULL,
    workflow_id uuid NOT NULL,
    node_id text NOT NULL,
    conversation_id text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    thread_subject text,
    last_message_id text
);

--
-- Name: apps; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE IF NOT EXISTS public.apps (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    title text NOT NULL,
    description text,
    subdomain text,
    other_domains text[],
    owner_id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    workflow_id uuid,
    node_id text,
    api_key_id uuid
);

--
-- Name: builder_input_links; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE IF NOT EXISTS public.builder_input_links (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid NOT NULL,
    workflow_id uuid NOT NULL,
    builder_conversation_id text NOT NULL,
    ask_id text NOT NULL,
    agent_conversation_id text,
    agent_node_id text,
    inputs jsonb NOT NULL,
    workflow_name text,
    status text DEFAULT 'pending'::text NOT NULL,
    answered_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    expires_at timestamp with time zone DEFAULT (now() + '7 days'::interval) NOT NULL,
    CONSTRAINT builder_input_links_status_check CHECK ((status = ANY (ARRAY['pending'::text, 'answered'::text, 'expired'::text])))
);

--
-- Name: builder_sessions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE IF NOT EXISTS public.builder_sessions (
    generation_id text NOT NULL,
    file_id text NOT NULL,
    conversation_id text,
    workflow_id uuid,
    user_id uuid,
    mode text DEFAULT 'generate'::text NOT NULL,
    brain_model text DEFAULT ''::text NOT NULL,
    first_prompt text DEFAULT ''::text NOT NULL,
    node_count integer DEFAULT 0 NOT NULL,
    total_cost numeric(12,6) DEFAULT 0 NOT NULL,
    total_tokens bigint DEFAULT 0 NOT NULL,
    total_duration_s numeric(12,2) DEFAULT 0 NOT NULL,
    file_size bigint DEFAULT 0 NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    success boolean,
    started_at timestamp with time zone DEFAULT now() NOT NULL,
    last_activity timestamp with time zone DEFAULT now() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);

--
-- Name: credential_refresh_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE IF NOT EXISTS public.credential_refresh_events (
    id bigint NOT NULL,
    ts timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    trace_id text,
    span_id text,
    credential_id uuid NOT NULL,
    user_id uuid,
    provider text NOT NULL,
    container_id text NOT NULL,
    process_pid integer NOT NULL,
    caller_path text NOT NULL,
    force_refresh boolean DEFAULT false NOT NULL,
    phase_outcome text NOT NULL,
    failure_mode_id text,
    started_at timestamp with time zone NOT NULL,
    ended_at timestamp with time zone NOT NULL,
    lock_wait_ms integer,
    loaded_updated_at timestamp with time zone,
    in_lock_reread_updated_at timestamp with time zone,
    retry_reread_updated_at timestamp with time zone,
    refresh_token_prefix_before text,
    refresh_token_prefix_after text,
    rotation_observed boolean,
    expires_at_before timestamp with time zone,
    expires_at_after timestamp with time zone,
    expires_in_seconds integer,
    scope_before text,
    scope_after text,
    token_kind_refreshed text,
    user_expires_at_after timestamp with time zone,
    http_status integer,
    http_response_ok_flag boolean,
    provider_error_code text,
    provider_error_description text,
    response_body_kind text,
    network_failure_kind text,
    request_duration_ms integer,
    modal_egress_ip inet,
    client_id_fingerprint text,
    instance_url text,
    persist_rows_affected integer,
    persist_error_class text,
    concurrent_writer_credential_id uuid,
    sibling_team_id text,
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL
);

--
-- Name: TABLE credential_refresh_events; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.credential_refresh_events IS 'Append-only audit of OAuth token refresh attempts. Written from utils/audit_pool.py on a dedicated asyncpg pool. Survives main-pool/pooler outages and SIGKILL between provider success and span flush. See backend/nodes/core/oauth_audit.py for the PhaseOutcome enum and the schema-of-record.';

--
-- Name: credential_refresh_events_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE IF NOT EXISTS public.credential_refresh_events_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

--
-- Name: credential_refresh_events_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.credential_refresh_events_id_seq OWNED BY public.credential_refresh_events.id;

--
-- Name: hosted_mcp_servers; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE IF NOT EXISTS public.hosted_mcp_servers (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid NOT NULL,
    workflow_id uuid NOT NULL,
    node_id text NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    last_used_at timestamp with time zone,
    call_count integer DEFAULT 0 NOT NULL
);

--
-- Name: mcp_feedback; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE IF NOT EXISTS public.mcp_feedback (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid NOT NULL,
    type text NOT NULL,
    title text NOT NULL,
    description text NOT NULL,
    workflow_id uuid,
    node_type text,
    mcp_client text,
    metadata jsonb DEFAULT '{}'::jsonb,
    created_at timestamp with time zone DEFAULT now(),
    priority integer DEFAULT 5 NOT NULL,
    priority_justification text DEFAULT ''::text NOT NULL,
    duplicate_count integer DEFAULT 1 NOT NULL,
    duplicate_submitters jsonb DEFAULT '[]'::jsonb NOT NULL,
    CONSTRAINT mcp_feedback_priority_range CHECK (((priority >= 1) AND (priority <= 10))),
    CONSTRAINT mcp_feedback_type_check CHECK ((type = ANY (ARRAY['bug'::text, 'feature_request'::text])))
);

--
-- Name: recurring_charges; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE IF NOT EXISTS public.recurring_charges (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid NOT NULL,
    credential_id uuid,
    charge_type text NOT NULL,
    hourly_amount numeric(12,6) NOT NULL,
    last_charged_at timestamp with time zone DEFAULT now() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    over_cap_since timestamp with time zone
);

--
-- Name: shared_run_links; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE IF NOT EXISTS public.shared_run_links (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid NOT NULL,
    workflow_id uuid NOT NULL,
    title text DEFAULT ''::text NOT NULL,
    snapshot jsonb NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);

--
-- Name: skill_user_mutes; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE IF NOT EXISTS public.skill_user_mutes (
    skill_id uuid NOT NULL,
    user_id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);

--
-- Name: skills; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE IF NOT EXISTS public.skills (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    owner_id uuid,
    organization_id uuid,
    is_system boolean DEFAULT false NOT NULL,
    name text NOT NULL,
    description text DEFAULT ''::text NOT NULL,
    body_text text,
    body_workflow jsonb,
    display_metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    enabled boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT skills_system_scope_check CHECK ((((is_system = true) AND (owner_id IS NULL) AND (organization_id IS NULL)) OR ((is_system = false) AND (owner_id IS NOT NULL) AND (organization_id IS NOT NULL))))
);

--
-- Name: template_votes; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE IF NOT EXISTS public.template_votes (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    template_id uuid NOT NULL,
    user_id uuid NOT NULL,
    vote_type smallint NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    CONSTRAINT template_votes_vote_type_check CHECK ((vote_type = ANY (ARRAY['-1'::integer, 1])))
);

--
-- Name: trigger_test_credentials; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE IF NOT EXISTS public.trigger_test_credentials (
    provider text NOT NULL,
    credential_id uuid,
    updated_by uuid NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    test_config jsonb DEFAULT '{}'::jsonb NOT NULL
);

--
-- Name: trigger_test_runs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE IF NOT EXISTS public.trigger_test_runs (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    provider text NOT NULL,
    test_name text NOT NULL,
    status text NOT NULL,
    started_at timestamp with time zone DEFAULT now() NOT NULL,
    finished_at timestamp with time zone,
    duration_ms integer,
    error text,
    output jsonb,
    triggered_by uuid,
    category text NOT NULL
);

--
-- Name: user_feedback; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE IF NOT EXISTS public.user_feedback (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid NOT NULL,
    type text DEFAULT 'general'::text NOT NULL,
    message text NOT NULL,
    page_url text,
    metadata jsonb DEFAULT '{}'::jsonb,
    created_at timestamp with time zone DEFAULT now(),
    CONSTRAINT user_feedback_type_check CHECK ((type = ANY (ARRAY['bug'::text, 'idea'::text, 'general'::text, 'agent_bug'::text])))
);

--
-- Name: user_login_stats; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE IF NOT EXISTS public.user_login_stats (
    user_id uuid NOT NULL,
    login_count integer DEFAULT 0 NOT NULL,
    last_login_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);

--
-- Name: user_onboarding_responses; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE IF NOT EXISTS public.user_onboarding_responses (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid NOT NULL,
    responses jsonb DEFAULT '{}'::jsonb NOT NULL,
    completed_at timestamp with time zone DEFAULT now() NOT NULL,
    version integer DEFAULT 1 NOT NULL,
    created_at timestamp with time zone DEFAULT now()
);

--
-- Name: workflow_build_requests; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE IF NOT EXISTS public.workflow_build_requests (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid NOT NULL,
    request_type text NOT NULL,
    prompt text NOT NULL,
    current_graph jsonb,
    current_graph_summary jsonb,
    target_node_ids text[],
    selected_node_id text,
    model text,
    generation_id text,
    success boolean,
    error_message text,
    result_graph jsonb,
    result_summary jsonb,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    duration_ms integer,
    CONSTRAINT workflow_build_requests_request_type_check CHECK ((request_type = ANY (ARRAY['generate'::text, 'edit'::text, 'chat'::text])))
);

--
-- Name: TABLE workflow_build_requests; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.workflow_build_requests IS 'Tracks AI-powered workflow generation requests for analytics. Captures what users are trying to build, success/failure rates, and common patterns.';

--
-- Name: COLUMN workflow_build_requests.prompt; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.workflow_build_requests.prompt IS 'Natural language prompt for generate requests, or edit instructions for edit requests';

--
-- Name: COLUMN workflow_build_requests.current_graph; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.workflow_build_requests.current_graph IS 'For edit requests: full workflow graph before editing';

--
-- Name: COLUMN workflow_build_requests.current_graph_summary; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.workflow_build_requests.current_graph_summary IS 'For edit requests: quick-access summary {node_count, edge_count, node_types}';

--
-- Name: COLUMN workflow_build_requests.result_graph; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.workflow_build_requests.result_graph IS 'Full generated workflow graph with nodes and edges';

--
-- Name: COLUMN workflow_build_requests.result_summary; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.workflow_build_requests.result_summary IS 'Quick-access summary: {node_count, edge_count, node_types}';

--
-- Name: workflow_embeddings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE IF NOT EXISTS public.workflow_embeddings (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    workflow_id uuid NOT NULL,
    owner_id uuid NOT NULL,
    organization_id uuid,
    composite_text text NOT NULL,
    structural_metadata jsonb DEFAULT '{}'::jsonb,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);

--
-- Name: workflow_templates; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE IF NOT EXISTS public.workflow_templates (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    workflow_id uuid NOT NULL,
    share_id uuid NOT NULL,
    title text NOT NULL,
    slug text NOT NULL,
    description text,
    view_count integer DEFAULT 0,
    fork_count integer DEFAULT 0,
    upvote_count integer DEFAULT 0,
    downvote_count integer DEFAULT 0,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    embedding_updated_at timestamp with time zone,
    structural_metadata jsonb DEFAULT '{}'::jsonb
);

--
-- Name: credential_refresh_events id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.credential_refresh_events ALTER COLUMN id SET DEFAULT nextval('public.credential_refresh_events_id_seq'::regclass);

--
-- Name: agent_email_replies agent_email_replies_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid
                   WHERE c.conname = 'agent_email_replies_pkey' AND t.relname = 'agent_email_replies') THEN
        ALTER TABLE ONLY public.agent_email_replies ADD CONSTRAINT agent_email_replies_pkey PRIMARY KEY (id);
    END IF;
END $$;

--
-- Name: apps apps_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid
                   WHERE c.conname = 'apps_pkey' AND t.relname = 'apps') THEN
        ALTER TABLE ONLY public.apps ADD CONSTRAINT apps_pkey PRIMARY KEY (id);
    END IF;
END $$;

--
-- Name: apps apps_subdomain_key; Type: CONSTRAINT; Schema: public; Owner: -
--

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid
                   WHERE c.conname = 'apps_subdomain_key' AND t.relname = 'apps') THEN
        ALTER TABLE ONLY public.apps ADD CONSTRAINT apps_subdomain_key UNIQUE (subdomain);
    END IF;
END $$;

--
-- Name: builder_input_links builder_input_links_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid
                   WHERE c.conname = 'builder_input_links_pkey' AND t.relname = 'builder_input_links') THEN
        ALTER TABLE ONLY public.builder_input_links ADD CONSTRAINT builder_input_links_pkey PRIMARY KEY (id);
    END IF;
END $$;

--
-- Name: builder_sessions builder_sessions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid
                   WHERE c.conname = 'builder_sessions_pkey' AND t.relname = 'builder_sessions') THEN
        ALTER TABLE ONLY public.builder_sessions ADD CONSTRAINT builder_sessions_pkey PRIMARY KEY (generation_id);
    END IF;
END $$;

--
-- Name: credential_refresh_events credential_refresh_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid
                   WHERE c.conname = 'credential_refresh_events_pkey' AND t.relname = 'credential_refresh_events') THEN
        ALTER TABLE ONLY public.credential_refresh_events ADD CONSTRAINT credential_refresh_events_pkey PRIMARY KEY (id);
    END IF;
END $$;

--
-- Name: hosted_mcp_servers hosted_mcp_servers_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid
                   WHERE c.conname = 'hosted_mcp_servers_pkey' AND t.relname = 'hosted_mcp_servers') THEN
        ALTER TABLE ONLY public.hosted_mcp_servers ADD CONSTRAINT hosted_mcp_servers_pkey PRIMARY KEY (id);
    END IF;
END $$;

--
-- Name: hosted_mcp_servers hosted_mcp_servers_workflow_id_node_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid
                   WHERE c.conname = 'hosted_mcp_servers_workflow_id_node_id_key' AND t.relname = 'hosted_mcp_servers') THEN
        ALTER TABLE ONLY public.hosted_mcp_servers ADD CONSTRAINT hosted_mcp_servers_workflow_id_node_id_key UNIQUE (workflow_id, node_id);
    END IF;
END $$;

--
-- Name: mcp_feedback mcp_feedback_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid
                   WHERE c.conname = 'mcp_feedback_pkey' AND t.relname = 'mcp_feedback') THEN
        ALTER TABLE ONLY public.mcp_feedback ADD CONSTRAINT mcp_feedback_pkey PRIMARY KEY (id);
    END IF;
END $$;

--
-- Name: recurring_charges recurring_charges_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid
                   WHERE c.conname = 'recurring_charges_pkey' AND t.relname = 'recurring_charges') THEN
        ALTER TABLE ONLY public.recurring_charges ADD CONSTRAINT recurring_charges_pkey PRIMARY KEY (id);
    END IF;
END $$;

--
-- Name: shared_run_links shared_run_links_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid
                   WHERE c.conname = 'shared_run_links_pkey' AND t.relname = 'shared_run_links') THEN
        ALTER TABLE ONLY public.shared_run_links ADD CONSTRAINT shared_run_links_pkey PRIMARY KEY (id);
    END IF;
END $$;

--
-- Name: skill_user_mutes skill_user_mutes_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid
                   WHERE c.conname = 'skill_user_mutes_pkey' AND t.relname = 'skill_user_mutes') THEN
        ALTER TABLE ONLY public.skill_user_mutes ADD CONSTRAINT skill_user_mutes_pkey PRIMARY KEY (skill_id, user_id);
    END IF;
END $$;

--
-- Name: skills skills_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid
                   WHERE c.conname = 'skills_pkey' AND t.relname = 'skills') THEN
        ALTER TABLE ONLY public.skills ADD CONSTRAINT skills_pkey PRIMARY KEY (id);
    END IF;
END $$;

--
-- Name: template_votes template_votes_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid
                   WHERE c.conname = 'template_votes_pkey' AND t.relname = 'template_votes') THEN
        ALTER TABLE ONLY public.template_votes ADD CONSTRAINT template_votes_pkey PRIMARY KEY (id);
    END IF;
END $$;

--
-- Name: template_votes template_votes_template_id_user_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid
                   WHERE c.conname = 'template_votes_template_id_user_id_key' AND t.relname = 'template_votes') THEN
        ALTER TABLE ONLY public.template_votes ADD CONSTRAINT template_votes_template_id_user_id_key UNIQUE (template_id, user_id);
    END IF;
END $$;

--
-- Name: trigger_test_credentials trigger_test_credentials_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid
                   WHERE c.conname = 'trigger_test_credentials_pkey' AND t.relname = 'trigger_test_credentials') THEN
        ALTER TABLE ONLY public.trigger_test_credentials ADD CONSTRAINT trigger_test_credentials_pkey PRIMARY KEY (provider);
    END IF;
END $$;

--
-- Name: trigger_test_runs trigger_test_runs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid
                   WHERE c.conname = 'trigger_test_runs_pkey' AND t.relname = 'trigger_test_runs') THEN
        ALTER TABLE ONLY public.trigger_test_runs ADD CONSTRAINT trigger_test_runs_pkey PRIMARY KEY (id);
    END IF;
END $$;

--
-- Name: user_onboarding_responses unique_user_onboarding; Type: CONSTRAINT; Schema: public; Owner: -
--

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid
                   WHERE c.conname = 'unique_user_onboarding' AND t.relname = 'user_onboarding_responses') THEN
        ALTER TABLE ONLY public.user_onboarding_responses ADD CONSTRAINT unique_user_onboarding UNIQUE (user_id);
    END IF;
END $$;

--
-- Name: user_feedback user_feedback_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid
                   WHERE c.conname = 'user_feedback_pkey' AND t.relname = 'user_feedback') THEN
        ALTER TABLE ONLY public.user_feedback ADD CONSTRAINT user_feedback_pkey PRIMARY KEY (id);
    END IF;
END $$;

--
-- Name: user_login_stats user_login_stats_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid
                   WHERE c.conname = 'user_login_stats_pkey' AND t.relname = 'user_login_stats') THEN
        ALTER TABLE ONLY public.user_login_stats ADD CONSTRAINT user_login_stats_pkey PRIMARY KEY (user_id);
    END IF;
END $$;

--
-- Name: user_onboarding_responses user_onboarding_responses_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid
                   WHERE c.conname = 'user_onboarding_responses_pkey' AND t.relname = 'user_onboarding_responses') THEN
        ALTER TABLE ONLY public.user_onboarding_responses ADD CONSTRAINT user_onboarding_responses_pkey PRIMARY KEY (id);
    END IF;
END $$;

--
-- Name: workflow_build_requests workflow_build_requests_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid
                   WHERE c.conname = 'workflow_build_requests_pkey' AND t.relname = 'workflow_build_requests') THEN
        ALTER TABLE ONLY public.workflow_build_requests ADD CONSTRAINT workflow_build_requests_pkey PRIMARY KEY (id);
    END IF;
END $$;

--
-- Name: workflow_embeddings workflow_embeddings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid
                   WHERE c.conname = 'workflow_embeddings_pkey' AND t.relname = 'workflow_embeddings') THEN
        ALTER TABLE ONLY public.workflow_embeddings ADD CONSTRAINT workflow_embeddings_pkey PRIMARY KEY (id);
    END IF;
END $$;

--
-- Name: workflow_embeddings workflow_embeddings_workflow_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid
                   WHERE c.conname = 'workflow_embeddings_workflow_id_key' AND t.relname = 'workflow_embeddings') THEN
        ALTER TABLE ONLY public.workflow_embeddings ADD CONSTRAINT workflow_embeddings_workflow_id_key UNIQUE (workflow_id);
    END IF;
END $$;

--
-- Name: workflow_templates workflow_templates_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid
                   WHERE c.conname = 'workflow_templates_pkey' AND t.relname = 'workflow_templates') THEN
        ALTER TABLE ONLY public.workflow_templates ADD CONSTRAINT workflow_templates_pkey PRIMARY KEY (id);
    END IF;
END $$;

--
-- Name: workflow_templates workflow_templates_slug_key; Type: CONSTRAINT; Schema: public; Owner: -
--

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid
                   WHERE c.conname = 'workflow_templates_slug_key' AND t.relname = 'workflow_templates') THEN
        ALTER TABLE ONLY public.workflow_templates ADD CONSTRAINT workflow_templates_slug_key UNIQUE (slug);
    END IF;
END $$;

--
-- Name: cre_audit_credential_ts; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX IF NOT EXISTS cre_audit_credential_ts ON public.credential_refresh_events USING btree (credential_id, ts DESC);

--
-- Name: cre_audit_outcome_ts; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX IF NOT EXISTS cre_audit_outcome_ts ON public.credential_refresh_events USING btree (phase_outcome, ts DESC) WHERE (phase_outcome <> ALL (ARRAY['refreshed'::text, 'in_lock_noop_fresh'::text, 'reused_db_value_after_failure'::text]));

--
-- Name: cre_audit_provider_egress_ts; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX IF NOT EXISTS cre_audit_provider_egress_ts ON public.credential_refresh_events USING btree (provider, modal_egress_ip, ts DESC);

--
-- Name: cre_audit_team_ts; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX IF NOT EXISTS cre_audit_team_ts ON public.credential_refresh_events USING btree (sibling_team_id, ts DESC) WHERE (sibling_team_id IS NOT NULL);

--
-- Name: cre_audit_trace; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX IF NOT EXISTS cre_audit_trace ON public.credential_refresh_events USING btree (trace_id) WHERE (trace_id IS NOT NULL);

--
-- Name: cre_audit_user_ts; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX IF NOT EXISTS cre_audit_user_ts ON public.credential_refresh_events USING btree (user_id, ts DESC) WHERE (user_id IS NOT NULL);

--
-- Name: idx_agent_email_replies_scope; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_email_replies_scope ON public.agent_email_replies USING btree (workflow_id, node_id, COALESCE(conversation_id, ''::text));

--
-- Name: idx_apps_owner_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX IF NOT EXISTS idx_apps_owner_id ON public.apps USING btree (owner_id);

--
-- Name: idx_apps_workflow_node; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX IF NOT EXISTS idx_apps_workflow_node ON public.apps USING btree (workflow_id, node_id);

--
-- Name: idx_builder_input_links_conversation; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX IF NOT EXISTS idx_builder_input_links_conversation ON public.builder_input_links USING btree (builder_conversation_id);

--
-- Name: idx_builder_sessions_file; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX IF NOT EXISTS idx_builder_sessions_file ON public.builder_sessions USING btree (file_id);

--
-- Name: idx_builder_sessions_last_activity; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX IF NOT EXISTS idx_builder_sessions_last_activity ON public.builder_sessions USING btree (last_activity DESC, generation_id DESC);

--
-- Name: idx_builder_sessions_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX IF NOT EXISTS idx_builder_sessions_user ON public.builder_sessions USING btree (user_id, last_activity DESC) WHERE (user_id IS NOT NULL);

--
-- Name: idx_hosted_mcp_servers_workflow; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX IF NOT EXISTS idx_hosted_mcp_servers_workflow ON public.hosted_mcp_servers USING btree (workflow_id);

--
-- Name: idx_mcp_feedback_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX IF NOT EXISTS idx_mcp_feedback_created ON public.mcp_feedback USING btree (created_at DESC);

--
-- Name: idx_mcp_feedback_embedding; Type: INDEX; Schema: public; Owner: -
--

--
-- Name: idx_mcp_feedback_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX IF NOT EXISTS idx_mcp_feedback_type ON public.mcp_feedback USING btree (type);

--
-- Name: idx_mcp_feedback_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX IF NOT EXISTS idx_mcp_feedback_user ON public.mcp_feedback USING btree (user_id);

--
-- Name: idx_onboarding_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX IF NOT EXISTS idx_onboarding_user ON public.user_onboarding_responses USING btree (user_id);

--
-- Name: idx_recurring_charges_active; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX IF NOT EXISTS idx_recurring_charges_active ON public.recurring_charges USING btree (user_id);

--
-- Name: idx_recurring_charges_credential; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX IF NOT EXISTS idx_recurring_charges_credential ON public.recurring_charges USING btree (credential_id);

--
-- Name: idx_shared_run_links_workflow; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX IF NOT EXISTS idx_shared_run_links_workflow ON public.shared_run_links USING btree (workflow_id);

--
-- Name: idx_skill_user_mutes_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX IF NOT EXISTS idx_skill_user_mutes_user ON public.skill_user_mutes USING btree (user_id);

--
-- Name: idx_skills_org; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX IF NOT EXISTS idx_skills_org ON public.skills USING btree (organization_id) WHERE (organization_id IS NOT NULL);

--
-- Name: idx_skills_org_owner; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX IF NOT EXISTS idx_skills_org_owner ON public.skills USING btree (organization_id, owner_id) WHERE (organization_id IS NOT NULL);

--
-- Name: idx_skills_system; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX IF NOT EXISTS idx_skills_system ON public.skills USING btree (is_system) WHERE (is_system = true);

--
-- Name: idx_skills_updated_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX IF NOT EXISTS idx_skills_updated_at ON public.skills USING btree (updated_at DESC);

--
-- Name: idx_template_votes_template_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX IF NOT EXISTS idx_template_votes_template_id ON public.template_votes USING btree (template_id);

--
-- Name: idx_template_votes_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX IF NOT EXISTS idx_template_votes_user_id ON public.template_votes USING btree (user_id);

--
-- Name: idx_trigger_test_runs_provider_category_started_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX IF NOT EXISTS idx_trigger_test_runs_provider_category_started_at ON public.trigger_test_runs USING btree (provider, category, started_at DESC);

--
-- Name: idx_trigger_test_runs_started_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX IF NOT EXISTS idx_trigger_test_runs_started_at ON public.trigger_test_runs USING btree (started_at DESC);

--
-- Name: idx_user_feedback_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX IF NOT EXISTS idx_user_feedback_created ON public.user_feedback USING btree (created_at DESC);

--
-- Name: idx_user_feedback_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX IF NOT EXISTS idx_user_feedback_type ON public.user_feedback USING btree (type);

--
-- Name: idx_user_feedback_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX IF NOT EXISTS idx_user_feedback_user ON public.user_feedback USING btree (user_id);

--
-- Name: idx_user_login_stats_last_login; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX IF NOT EXISTS idx_user_login_stats_last_login ON public.user_login_stats USING btree (last_login_at);

--
-- Name: idx_workflow_build_requests_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX IF NOT EXISTS idx_workflow_build_requests_created_at ON public.workflow_build_requests USING btree (created_at DESC);

--
-- Name: idx_workflow_build_requests_prompt_gin; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX IF NOT EXISTS idx_workflow_build_requests_prompt_gin ON public.workflow_build_requests USING gin (to_tsvector('english'::regconfig, prompt));

--
-- Name: idx_workflow_build_requests_success; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX IF NOT EXISTS idx_workflow_build_requests_success ON public.workflow_build_requests USING btree (success) WHERE (success = false);

--
-- Name: idx_workflow_build_requests_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX IF NOT EXISTS idx_workflow_build_requests_type ON public.workflow_build_requests USING btree (request_type);

--
-- Name: idx_workflow_build_requests_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX IF NOT EXISTS idx_workflow_build_requests_user_id ON public.workflow_build_requests USING btree (user_id);

--
-- Name: idx_workflow_embeddings_embedding; Type: INDEX; Schema: public; Owner: -
--

--
-- Name: idx_workflow_embeddings_org; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX IF NOT EXISTS idx_workflow_embeddings_org ON public.workflow_embeddings USING btree (organization_id);

--
-- Name: idx_workflow_embeddings_owner; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX IF NOT EXISTS idx_workflow_embeddings_owner ON public.workflow_embeddings USING btree (owner_id);

--
-- Name: idx_workflow_templates_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX IF NOT EXISTS idx_workflow_templates_created_at ON public.workflow_templates USING btree (created_at DESC);

--
-- Name: idx_workflow_templates_embedding; Type: INDEX; Schema: public; Owner: -
--

--
-- Name: idx_workflow_templates_slug; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX IF NOT EXISTS idx_workflow_templates_slug ON public.workflow_templates USING btree (slug);

--
-- Name: idx_workflow_templates_workflow_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX IF NOT EXISTS idx_workflow_templates_workflow_id ON public.workflow_templates USING btree (workflow_id);

--
-- Name: template_votes template_votes_count_trigger; Type: TRIGGER; Schema: public; Owner: -
--

DROP TRIGGER IF EXISTS template_votes_count_trigger ON public.template_votes;
CREATE TRIGGER template_votes_count_trigger AFTER INSERT OR DELETE OR UPDATE ON public.template_votes FOR EACH ROW EXECUTE FUNCTION public.update_template_vote_counts();

--
-- Name: template_votes template_votes_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

DROP TRIGGER IF EXISTS template_votes_updated_at ON public.template_votes;
CREATE TRIGGER template_votes_updated_at BEFORE UPDATE ON public.template_votes FOR EACH ROW EXECUTE FUNCTION public.update_template_vote_updated_at();

--
-- Name: skills update_skills_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

DROP TRIGGER IF EXISTS update_skills_updated_at ON public.skills;
CREATE TRIGGER update_skills_updated_at BEFORE UPDATE ON public.skills FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

--
-- Name: workflow_embeddings workflow_embeddings_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

DROP TRIGGER IF EXISTS workflow_embeddings_updated_at ON public.workflow_embeddings;
CREATE TRIGGER workflow_embeddings_updated_at BEFORE UPDATE ON public.workflow_embeddings FOR EACH ROW EXECUTE FUNCTION public.update_workflow_embeddings_updated_at();

--
-- Name: workflow_templates workflow_templates_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

DROP TRIGGER IF EXISTS workflow_templates_updated_at ON public.workflow_templates;
CREATE TRIGGER workflow_templates_updated_at BEFORE UPDATE ON public.workflow_templates FOR EACH ROW EXECUTE FUNCTION public.update_workflow_template_updated_at();

--
-- Name: agent_email_replies agent_email_replies_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid
                   WHERE c.conname = 'agent_email_replies_user_id_fkey' AND t.relname = 'agent_email_replies') THEN
        ALTER TABLE ONLY public.agent_email_replies ADD CONSTRAINT agent_email_replies_user_id_fkey FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE CASCADE;
    END IF;
END $$;

--
-- Name: apps apps_api_key_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid
                   WHERE c.conname = 'apps_api_key_id_fkey' AND t.relname = 'apps') THEN
        ALTER TABLE ONLY public.apps ADD CONSTRAINT apps_api_key_id_fkey FOREIGN KEY (api_key_id) REFERENCES public.api_keys(id) ON DELETE SET NULL;
    END IF;
END $$;

--
-- Name: apps apps_owner_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid
                   WHERE c.conname = 'apps_owner_id_fkey' AND t.relname = 'apps') THEN
        ALTER TABLE ONLY public.apps ADD CONSTRAINT apps_owner_id_fkey FOREIGN KEY (owner_id) REFERENCES auth.users(id) ON DELETE CASCADE;
    END IF;
END $$;

--
-- Name: apps apps_workflow_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid
                   WHERE c.conname = 'apps_workflow_id_fkey' AND t.relname = 'apps') THEN
        ALTER TABLE ONLY public.apps ADD CONSTRAINT apps_workflow_id_fkey FOREIGN KEY (workflow_id) REFERENCES public.workflows(id) ON DELETE CASCADE;
    END IF;
END $$;

--
-- Name: builder_input_links builder_input_links_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid
                   WHERE c.conname = 'builder_input_links_user_id_fkey' AND t.relname = 'builder_input_links') THEN
        ALTER TABLE ONLY public.builder_input_links ADD CONSTRAINT builder_input_links_user_id_fkey FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE CASCADE;
    END IF;
END $$;

--
-- Name: builder_sessions builder_sessions_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid
                   WHERE c.conname = 'builder_sessions_user_id_fkey' AND t.relname = 'builder_sessions') THEN
        ALTER TABLE ONLY public.builder_sessions ADD CONSTRAINT builder_sessions_user_id_fkey FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE SET NULL;
    END IF;
END $$;

--
-- Name: mcp_feedback mcp_feedback_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid
                   WHERE c.conname = 'mcp_feedback_user_id_fkey' AND t.relname = 'mcp_feedback') THEN
        ALTER TABLE ONLY public.mcp_feedback ADD CONSTRAINT mcp_feedback_user_id_fkey FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE CASCADE;
    END IF;
END $$;

--
-- Name: recurring_charges recurring_charges_credential_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid
                   WHERE c.conname = 'recurring_charges_credential_id_fkey' AND t.relname = 'recurring_charges') THEN
        ALTER TABLE ONLY public.recurring_charges ADD CONSTRAINT recurring_charges_credential_id_fkey FOREIGN KEY (credential_id) REFERENCES public.credentials(id) ON DELETE CASCADE;
    END IF;
END $$;

--
-- Name: skill_user_mutes skill_user_mutes_skill_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid
                   WHERE c.conname = 'skill_user_mutes_skill_id_fkey' AND t.relname = 'skill_user_mutes') THEN
        ALTER TABLE ONLY public.skill_user_mutes ADD CONSTRAINT skill_user_mutes_skill_id_fkey FOREIGN KEY (skill_id) REFERENCES public.skills(id) ON DELETE CASCADE;
    END IF;
END $$;

--
-- Name: skill_user_mutes skill_user_mutes_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid
                   WHERE c.conname = 'skill_user_mutes_user_id_fkey' AND t.relname = 'skill_user_mutes') THEN
        ALTER TABLE ONLY public.skill_user_mutes ADD CONSTRAINT skill_user_mutes_user_id_fkey FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE CASCADE;
    END IF;
END $$;

--
-- Name: skills skills_organization_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid
                   WHERE c.conname = 'skills_organization_id_fkey' AND t.relname = 'skills') THEN
        ALTER TABLE ONLY public.skills ADD CONSTRAINT skills_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES public.organizations(id) ON DELETE CASCADE;
    END IF;
END $$;

--
-- Name: skills skills_owner_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid
                   WHERE c.conname = 'skills_owner_id_fkey' AND t.relname = 'skills') THEN
        ALTER TABLE ONLY public.skills ADD CONSTRAINT skills_owner_id_fkey FOREIGN KEY (owner_id) REFERENCES auth.users(id) ON DELETE RESTRICT;
    END IF;
END $$;

--
-- Name: template_votes template_votes_template_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid
                   WHERE c.conname = 'template_votes_template_id_fkey' AND t.relname = 'template_votes') THEN
        ALTER TABLE ONLY public.template_votes ADD CONSTRAINT template_votes_template_id_fkey FOREIGN KEY (template_id) REFERENCES public.workflow_templates(id) ON DELETE CASCADE;
    END IF;
END $$;

--
-- Name: template_votes template_votes_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid
                   WHERE c.conname = 'template_votes_user_id_fkey' AND t.relname = 'template_votes') THEN
        ALTER TABLE ONLY public.template_votes ADD CONSTRAINT template_votes_user_id_fkey FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE CASCADE;
    END IF;
END $$;

--
-- Name: trigger_test_credentials trigger_test_credentials_credential_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid
                   WHERE c.conname = 'trigger_test_credentials_credential_id_fkey' AND t.relname = 'trigger_test_credentials') THEN
        ALTER TABLE ONLY public.trigger_test_credentials ADD CONSTRAINT trigger_test_credentials_credential_id_fkey FOREIGN KEY (credential_id) REFERENCES public.credentials(id) ON DELETE SET NULL;
    END IF;
END $$;

--
-- Name: trigger_test_credentials trigger_test_credentials_updated_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid
                   WHERE c.conname = 'trigger_test_credentials_updated_by_fkey' AND t.relname = 'trigger_test_credentials') THEN
        ALTER TABLE ONLY public.trigger_test_credentials ADD CONSTRAINT trigger_test_credentials_updated_by_fkey FOREIGN KEY (updated_by) REFERENCES auth.users(id) ON DELETE CASCADE;
    END IF;
END $$;

--
-- Name: trigger_test_runs trigger_test_runs_triggered_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid
                   WHERE c.conname = 'trigger_test_runs_triggered_by_fkey' AND t.relname = 'trigger_test_runs') THEN
        ALTER TABLE ONLY public.trigger_test_runs ADD CONSTRAINT trigger_test_runs_triggered_by_fkey FOREIGN KEY (triggered_by) REFERENCES auth.users(id) ON DELETE SET NULL;
    END IF;
END $$;

--
-- Name: user_feedback user_feedback_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid
                   WHERE c.conname = 'user_feedback_user_id_fkey' AND t.relname = 'user_feedback') THEN
        ALTER TABLE ONLY public.user_feedback ADD CONSTRAINT user_feedback_user_id_fkey FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE CASCADE;
    END IF;
END $$;

--
-- Name: user_login_stats user_login_stats_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid
                   WHERE c.conname = 'user_login_stats_user_id_fkey' AND t.relname = 'user_login_stats') THEN
        ALTER TABLE ONLY public.user_login_stats ADD CONSTRAINT user_login_stats_user_id_fkey FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE CASCADE;
    END IF;
END $$;

--
-- Name: user_onboarding_responses user_onboarding_responses_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid
                   WHERE c.conname = 'user_onboarding_responses_user_id_fkey' AND t.relname = 'user_onboarding_responses') THEN
        ALTER TABLE ONLY public.user_onboarding_responses ADD CONSTRAINT user_onboarding_responses_user_id_fkey FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE CASCADE;
    END IF;
END $$;

--
-- Name: workflow_build_requests workflow_build_requests_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid
                   WHERE c.conname = 'workflow_build_requests_user_id_fkey' AND t.relname = 'workflow_build_requests') THEN
        ALTER TABLE ONLY public.workflow_build_requests ADD CONSTRAINT workflow_build_requests_user_id_fkey FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE CASCADE;
    END IF;
END $$;

--
-- Name: workflow_embeddings workflow_embeddings_owner_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid
                   WHERE c.conname = 'workflow_embeddings_owner_id_fkey' AND t.relname = 'workflow_embeddings') THEN
        ALTER TABLE ONLY public.workflow_embeddings ADD CONSTRAINT workflow_embeddings_owner_id_fkey FOREIGN KEY (owner_id) REFERENCES auth.users(id) ON DELETE CASCADE;
    END IF;
END $$;

--
-- Name: workflow_embeddings workflow_embeddings_workflow_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid
                   WHERE c.conname = 'workflow_embeddings_workflow_id_fkey' AND t.relname = 'workflow_embeddings') THEN
        ALTER TABLE ONLY public.workflow_embeddings ADD CONSTRAINT workflow_embeddings_workflow_id_fkey FOREIGN KEY (workflow_id) REFERENCES public.workflows(id) ON DELETE CASCADE;
    END IF;
END $$;

--
-- Name: workflow_templates workflow_templates_share_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid
                   WHERE c.conname = 'workflow_templates_share_id_fkey' AND t.relname = 'workflow_templates') THEN
        ALTER TABLE ONLY public.workflow_templates ADD CONSTRAINT workflow_templates_share_id_fkey FOREIGN KEY (share_id) REFERENCES public.resource_shares(id) ON DELETE CASCADE;
    END IF;
END $$;

--
-- Name: workflow_templates workflow_templates_workflow_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid
                   WHERE c.conname = 'workflow_templates_workflow_id_fkey' AND t.relname = 'workflow_templates') THEN
        ALTER TABLE ONLY public.workflow_templates ADD CONSTRAINT workflow_templates_workflow_id_fkey FOREIGN KEY (workflow_id) REFERENCES public.workflows(id) ON DELETE CASCADE;
    END IF;
END $$;

-- Builder sessions contain prompts, model choices and cost data. The backend
-- mediates access; browser API roles must not query or mutate them directly.
REVOKE ALL ON TABLE public.builder_sessions FROM anon, authenticated;
DROP POLICY IF EXISTS "Service role full access to builder sessions" ON public.builder_sessions;
CREATE POLICY "Service role full access to builder sessions" ON public.builder_sessions TO service_role USING (true) WITH CHECK (true);

--
-- Name: recurring_charges Service role full access; Type: POLICY; Schema: public; Owner: -
--

DROP POLICY IF EXISTS "Service role full access" ON public.recurring_charges;
CREATE POLICY "Service role full access" ON public.recurring_charges USING (true) WITH CHECK (true);

--
-- Name: user_onboarding_responses Service role full access to onboarding; Type: POLICY; Schema: public; Owner: -
--

DROP POLICY IF EXISTS "Service role full access to onboarding" ON public.user_onboarding_responses;
CREATE POLICY "Service role full access to onboarding" ON public.user_onboarding_responses TO service_role USING (true);

--
-- Name: workflow_build_requests Service role has full access; Type: POLICY; Schema: public; Owner: -
--

DROP POLICY IF EXISTS "Service role has full access" ON public.workflow_build_requests;
CREATE POLICY "Service role has full access" ON public.workflow_build_requests TO service_role USING (true) WITH CHECK (true);

--
-- Name: user_onboarding_responses Users can insert own onboarding; Type: POLICY; Schema: public; Owner: -
--

DROP POLICY IF EXISTS "Users can insert own onboarding" ON public.user_onboarding_responses;
CREATE POLICY "Users can insert own onboarding" ON public.user_onboarding_responses FOR INSERT TO authenticated WITH CHECK ((user_id = auth.uid()));

--
-- Name: user_onboarding_responses Users can view own onboarding; Type: POLICY; Schema: public; Owner: -
--

DROP POLICY IF EXISTS "Users can view own onboarding" ON public.user_onboarding_responses;
CREATE POLICY "Users can view own onboarding" ON public.user_onboarding_responses FOR SELECT USING ((user_id = auth.uid()));

--
-- Name: workflow_build_requests Users can view their own requests; Type: POLICY; Schema: public; Owner: -
--

DROP POLICY IF EXISTS "Users can view their own requests" ON public.workflow_build_requests;
CREATE POLICY "Users can view their own requests" ON public.workflow_build_requests FOR SELECT TO authenticated USING ((auth.uid() = user_id));

--
-- Name: agent_email_replies; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.agent_email_replies ENABLE ROW LEVEL SECURITY;

--
-- Name: apps; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.apps ENABLE ROW LEVEL SECURITY;

--
-- Name: builder_input_links; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.builder_input_links ENABLE ROW LEVEL SECURITY;

--
-- Name: builder_sessions; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.builder_sessions ENABLE ROW LEVEL SECURITY;

--
-- Name: credential_refresh_events; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.credential_refresh_events ENABLE ROW LEVEL SECURITY;

--
-- Name: hosted_mcp_servers; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.hosted_mcp_servers ENABLE ROW LEVEL SECURITY;

--
-- Name: mcp_feedback; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.mcp_feedback ENABLE ROW LEVEL SECURITY;

--
-- Name: mcp_feedback mcp_feedback_insert; Type: POLICY; Schema: public; Owner: -
--

DROP POLICY IF EXISTS mcp_feedback_insert ON public.mcp_feedback;
CREATE POLICY mcp_feedback_insert ON public.mcp_feedback FOR INSERT WITH CHECK ((auth.uid() = user_id));

--
-- Name: mcp_feedback mcp_feedback_select; Type: POLICY; Schema: public; Owner: -
--

DROP POLICY IF EXISTS mcp_feedback_select ON public.mcp_feedback;
CREATE POLICY mcp_feedback_select ON public.mcp_feedback FOR SELECT USING ((auth.uid() = user_id));

--
-- Name: mcp_feedback mcp_feedback_service; Type: POLICY; Schema: public; Owner: -
--

DROP POLICY IF EXISTS mcp_feedback_service ON public.mcp_feedback;
CREATE POLICY mcp_feedback_service ON public.mcp_feedback TO service_role USING (true) WITH CHECK (true);

--
-- Name: recurring_charges; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.recurring_charges ENABLE ROW LEVEL SECURITY;

--
-- Name: shared_run_links; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.shared_run_links ENABLE ROW LEVEL SECURITY;

--
-- Name: skill_user_mutes; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.skill_user_mutes ENABLE ROW LEVEL SECURITY;

--
-- Name: skills; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.skills ENABLE ROW LEVEL SECURITY;

--
-- Name: template_votes; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.template_votes ENABLE ROW LEVEL SECURITY;

--
-- Name: template_votes template_votes_public_read; Type: POLICY; Schema: public; Owner: -
--

DROP POLICY IF EXISTS template_votes_public_read ON public.template_votes;
CREATE POLICY template_votes_public_read ON public.template_votes FOR SELECT USING (true);

--
-- Name: template_votes template_votes_user_delete; Type: POLICY; Schema: public; Owner: -
--

DROP POLICY IF EXISTS template_votes_user_delete ON public.template_votes;
CREATE POLICY template_votes_user_delete ON public.template_votes FOR DELETE USING ((user_id = auth.uid()));

--
-- Name: template_votes template_votes_user_insert; Type: POLICY; Schema: public; Owner: -
--

DROP POLICY IF EXISTS template_votes_user_insert ON public.template_votes;
CREATE POLICY template_votes_user_insert ON public.template_votes FOR INSERT WITH CHECK ((user_id = auth.uid()));

--
-- Name: template_votes template_votes_user_update; Type: POLICY; Schema: public; Owner: -
--

DROP POLICY IF EXISTS template_votes_user_update ON public.template_votes;
CREATE POLICY template_votes_user_update ON public.template_votes FOR UPDATE USING ((user_id = auth.uid()));

--
-- Name: trigger_test_credentials; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.trigger_test_credentials ENABLE ROW LEVEL SECURITY;

--
-- Name: trigger_test_runs; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.trigger_test_runs ENABLE ROW LEVEL SECURITY;

--
-- Name: user_feedback; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.user_feedback ENABLE ROW LEVEL SECURITY;

--
-- Name: user_feedback user_feedback_insert; Type: POLICY; Schema: public; Owner: -
--

DROP POLICY IF EXISTS user_feedback_insert ON public.user_feedback;
CREATE POLICY user_feedback_insert ON public.user_feedback FOR INSERT WITH CHECK ((auth.uid() = user_id));

--
-- Name: user_feedback user_feedback_select; Type: POLICY; Schema: public; Owner: -
--

DROP POLICY IF EXISTS user_feedback_select ON public.user_feedback;
CREATE POLICY user_feedback_select ON public.user_feedback FOR SELECT USING ((auth.uid() = user_id));

--
-- Name: user_feedback user_feedback_service; Type: POLICY; Schema: public; Owner: -
--

DROP POLICY IF EXISTS user_feedback_service ON public.user_feedback;
CREATE POLICY user_feedback_service ON public.user_feedback TO service_role USING (true) WITH CHECK (true);

--
-- Name: user_login_stats; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.user_login_stats ENABLE ROW LEVEL SECURITY;

--
-- Name: user_onboarding_responses; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.user_onboarding_responses ENABLE ROW LEVEL SECURITY;

--
-- Name: workflow_build_requests; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.workflow_build_requests ENABLE ROW LEVEL SECURITY;

--
-- Name: workflow_embeddings; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.workflow_embeddings ENABLE ROW LEVEL SECURITY;

--
-- Name: workflow_embeddings workflow_embeddings_service_all; Type: POLICY; Schema: public; Owner: -
--

DROP POLICY IF EXISTS workflow_embeddings_service_all ON public.workflow_embeddings;
CREATE POLICY workflow_embeddings_service_all ON public.workflow_embeddings USING (true) WITH CHECK (true);

--
-- Name: workflow_templates; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.workflow_templates ENABLE ROW LEVEL SECURITY;

--
-- Name: workflow_templates workflow_templates_owner_delete; Type: POLICY; Schema: public; Owner: -
--

DROP POLICY IF EXISTS workflow_templates_owner_delete ON public.workflow_templates;
CREATE POLICY workflow_templates_owner_delete ON public.workflow_templates FOR DELETE USING ((EXISTS ( SELECT 1
   FROM public.workflows w
  WHERE ((w.id = workflow_templates.workflow_id) AND (w.owner_id = auth.uid())))));

--
-- Name: workflow_templates workflow_templates_owner_insert; Type: POLICY; Schema: public; Owner: -
--

DROP POLICY IF EXISTS workflow_templates_owner_insert ON public.workflow_templates;
CREATE POLICY workflow_templates_owner_insert ON public.workflow_templates FOR INSERT WITH CHECK ((EXISTS ( SELECT 1
   FROM public.workflows w
  WHERE ((w.id = workflow_templates.workflow_id) AND (w.owner_id = auth.uid())))));

--
-- Name: workflow_templates workflow_templates_owner_update; Type: POLICY; Schema: public; Owner: -
--

DROP POLICY IF EXISTS workflow_templates_owner_update ON public.workflow_templates;
CREATE POLICY workflow_templates_owner_update ON public.workflow_templates FOR UPDATE USING ((EXISTS ( SELECT 1
   FROM public.workflows w
  WHERE ((w.id = workflow_templates.workflow_id) AND (w.owner_id = auth.uid())))));

--
-- Name: workflow_templates workflow_templates_public_read; Type: POLICY; Schema: public; Owner: -
--

DROP POLICY IF EXISTS workflow_templates_public_read ON public.workflow_templates;
CREATE POLICY workflow_templates_public_read ON public.workflow_templates FOR SELECT USING (true);

--
-- Name: TABLE apps; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.apps TO service_role;

--
-- Name: TABLE credential_refresh_events; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,INSERT ON TABLE public.credential_refresh_events TO service_role;

--
-- Name: SEQUENCE credential_refresh_events_id_seq; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,USAGE ON SEQUENCE public.credential_refresh_events_id_seq TO service_role;

--
-- Name: TABLE skill_user_mutes; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.skill_user_mutes TO service_role;

--
-- Name: TABLE skills; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.skills TO service_role;

--
-- Name: TABLE trigger_test_credentials; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.trigger_test_credentials TO service_role;

--
-- Name: TABLE trigger_test_runs; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.trigger_test_runs TO service_role;

--
-- Name: TABLE user_login_stats; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.user_login_stats TO service_role;

--
-- Name: TABLE user_onboarding_responses; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,INSERT ON TABLE public.user_onboarding_responses TO authenticated;
GRANT ALL ON TABLE public.user_onboarding_responses TO service_role;

--
-- Name: TABLE workflow_build_requests; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.workflow_build_requests TO anon;
GRANT ALL ON TABLE public.workflow_build_requests TO authenticated;
GRANT ALL ON TABLE public.workflow_build_requests TO service_role;

--
-- Name: TABLE workflow_embeddings; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.workflow_embeddings TO service_role;
GRANT SELECT ON TABLE public.workflow_embeddings TO authenticated;

--
-- PostgreSQL database dump complete
--

-- Columns added to tables the schema already has.
ALTER TABLE public.organizations ADD COLUMN IF NOT EXISTS stripe_customer_id text;
ALTER TABLE public.organizations ADD COLUMN IF NOT EXISTS subscription_tier text DEFAULT 'free'::text NOT NULL;
ALTER TABLE public.organizations DROP CONSTRAINT IF EXISTS organizations_subscription_tier_check;
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid
                   WHERE c.conname = 'organizations_subscription_tier_check' AND t.relname = 'organizations') THEN
        ALTER TABLE public.organizations ADD CONSTRAINT organizations_subscription_tier_check CHECK ((subscription_tier = ANY (ARRAY['free'::text, 'plus'::text, 'pro'::text, 'enterprise'::text])));
    END IF;
END $$;
ALTER TABLE public.workflow_node_output_schemas ADD COLUMN IF NOT EXISTS sample_config jsonb;
ALTER TABLE public.workflow_node_output_schemas ADD COLUMN IF NOT EXISTS sample_output_clipped jsonb;
ALTER TABLE public.workflows ADD COLUMN IF NOT EXISTS template_draft jsonb;

-- Three of these carry an embedding, and this edition's Postgres image does not
-- ship pgvector. The tables are created without it and the column is added only
-- where the extension is actually available, so vector search is the single
-- thing that degrades rather than the whole migration failing.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_available_extensions WHERE name = 'vector') THEN
        CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;

        ALTER TABLE public.mcp_feedback ADD COLUMN IF NOT EXISTS embedding public.vector(1536);
        ALTER TABLE public.workflow_templates ADD COLUMN IF NOT EXISTS embedding public.vector(1536);
        ALTER TABLE public.workflow_embeddings ADD COLUMN IF NOT EXISTS embedding public.vector(1536);

        CREATE INDEX IF NOT EXISTS idx_mcp_feedback_embedding ON public.mcp_feedback
            USING hnsw (embedding public.vector_cosine_ops) WITH (m='16', ef_construction='64');
        CREATE INDEX IF NOT EXISTS idx_workflow_templates_embedding ON public.workflow_templates
            USING hnsw (embedding public.vector_cosine_ops) WITH (m='16', ef_construction='64');
        CREATE INDEX IF NOT EXISTS idx_workflow_embeddings_embedding ON public.workflow_embeddings
            USING hnsw (embedding public.vector_cosine_ops) WITH (m='16', ef_construction='64');
    END IF;
END $$;


-- The curated dump froze workflow_executions' trigger_source at a list that
-- omits two values the shipped backend writes: an agent answering an email
-- (agent_email_reply) and a headless builder run reporting back
-- (builder_event). Both would be rejected by the constraint, so the execution
-- row never lands and the run has no record.
--
-- graph_event is kept although nothing writes it, so this cannot fail against
-- rows an existing installation already has.
ALTER TABLE public.workflow_executions
    DROP CONSTRAINT IF EXISTS workflow_executions_trigger_source_check;
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid
                   WHERE c.conname = 'workflow_executions_trigger_source_check' AND t.relname = 'workflow_executions') THEN
        ALTER TABLE public.workflow_executions ADD CONSTRAINT workflow_executions_trigger_source_check CHECK (trigger_source IN ('manual', 'webhook', 'cron', 'mcp', 'api', 'email', 'agent_turn', 'shared_agent', 'builder_event', 'agent_email_reply', 'error_handler', 'graph_event'));
    END IF;
END $$;

-- Hardening for builder_sessions, which the reviewed base schema's hardening
-- migration could not touch because this file is what creates the table.
DROP POLICY IF EXISTS "Allow all for authenticated users" ON public.builder_sessions;
REVOKE ALL ON TABLE public.builder_sessions FROM anon, authenticated;
DROP POLICY IF EXISTS "Service role full access to builder sessions" ON public.builder_sessions;
CREATE POLICY "Service role full access to builder sessions"
    ON public.builder_sessions TO service_role USING (true) WITH CHECK (true);
