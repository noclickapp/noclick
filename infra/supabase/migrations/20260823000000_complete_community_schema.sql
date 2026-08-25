-- Community runtime additions that are not part of the curated base schema.
--
-- This migration is deliberately authored from the SQL contracts in the
-- surviving repositories. Keep the table set small: adding a table here is a
-- publication-boundary decision and must be added to the OSS schema allowlist.

-- Workflow database forks materialize their rows in this schema.
CREATE SCHEMA IF NOT EXISTS user_tables;
GRANT USAGE, CREATE ON SCHEMA user_tables TO service_role;


-- Durable reply capabilities for the agent-to-owner email channel.
CREATE TABLE IF NOT EXISTS public.agent_email_replies (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    workflow_id uuid NOT NULL,
    node_id text NOT NULL,
    conversation_id text,
    created_at timestamptz NOT NULL DEFAULT now(),
    thread_subject text,
    last_message_id text
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_email_replies_scope
    ON public.agent_email_replies (
        workflow_id,
        node_id,
        COALESCE(conversation_id, ''::text)
    );


-- Public capability links used to answer a parked workflow-builder question.
CREATE TABLE IF NOT EXISTS public.builder_input_links (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    workflow_id uuid NOT NULL,
    builder_conversation_id text NOT NULL,
    ask_id text NOT NULL,
    agent_conversation_id text,
    agent_node_id text,
    inputs jsonb NOT NULL,
    workflow_name text,
    status text NOT NULL DEFAULT 'pending',
    answered_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL DEFAULT (now() + interval '7 days'),
    CONSTRAINT builder_input_links_status_check
        CHECK (status IN ('pending', 'answered', 'expired'))
);

CREATE INDEX IF NOT EXISTS idx_builder_input_links_conversation
    ON public.builder_input_links (builder_conversation_id);


-- Immutable display snapshots shared from a completed test run.
CREATE TABLE IF NOT EXISTS public.shared_run_links (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL,
    workflow_id uuid NOT NULL,
    title text NOT NULL DEFAULT '',
    snapshot jsonb NOT NULL,
    is_active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_shared_run_links_workflow
    ON public.shared_run_links (workflow_id);


-- Reusable workflow-builder guidance owned by a user or an organization.
CREATE TABLE IF NOT EXISTS public.skills (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id uuid REFERENCES auth.users(id) ON DELETE RESTRICT,
    organization_id uuid REFERENCES public.organizations(id) ON DELETE CASCADE,
    is_system boolean NOT NULL DEFAULT false,
    name text NOT NULL,
    description text NOT NULL DEFAULT '',
    body_text text,
    body_workflow jsonb,
    display_metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    enabled boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT skills_system_scope_check CHECK (
        (is_system = true AND owner_id IS NULL AND organization_id IS NULL)
        OR
        (is_system = false AND owner_id IS NOT NULL AND organization_id IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_skills_org
    ON public.skills (organization_id)
    WHERE organization_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_skills_org_owner
    ON public.skills (organization_id, owner_id)
    WHERE organization_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_skills_system
    ON public.skills (is_system)
    WHERE is_system = true;
CREATE INDEX IF NOT EXISTS idx_skills_updated_at
    ON public.skills (updated_at DESC);

DROP TRIGGER IF EXISTS update_skills_updated_at ON public.skills;
CREATE TRIGGER update_skills_updated_at
    BEFORE UPDATE ON public.skills
    FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();


CREATE TABLE IF NOT EXISTS public.skill_user_mutes (
    skill_id uuid NOT NULL REFERENCES public.skills(id) ON DELETE CASCADE,
    user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT skill_user_mutes_pkey PRIMARY KEY (skill_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_skill_user_mutes_user
    ON public.skill_user_mutes (user_id);


-- Feedback is retained on the installation that received it.
CREATE TABLE IF NOT EXISTS public.user_feedback (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    type text NOT NULL DEFAULT 'general',
    message text NOT NULL,
    page_url text,
    metadata jsonb DEFAULT '{}'::jsonb,
    created_at timestamptz DEFAULT now(),
    CONSTRAINT user_feedback_type_check
        CHECK (type IN ('bug', 'idea', 'general', 'agent_bug'))
);

CREATE INDEX IF NOT EXISTS idx_user_feedback_user
    ON public.user_feedback (user_id);
CREATE INDEX IF NOT EXISTS idx_user_feedback_type
    ON public.user_feedback (type);
CREATE INDEX IF NOT EXISTS idx_user_feedback_created
    ON public.user_feedback (created_at DESC);


CREATE TABLE IF NOT EXISTS public.user_onboarding_responses (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    responses jsonb NOT NULL DEFAULT '{}'::jsonb,
    completed_at timestamptz NOT NULL DEFAULT now(),
    version integer NOT NULL DEFAULT 1,
    created_at timestamptz DEFAULT now(),
    CONSTRAINT unique_user_onboarding UNIQUE (user_id)
);

CREATE INDEX IF NOT EXISTS idx_onboarding_user
    ON public.user_onboarding_responses (user_id);


-- Skills use the existing resource-share model.
ALTER TABLE public.resource_shares
    DROP CONSTRAINT IF EXISTS resource_shares_resource_type_check;
ALTER TABLE public.resource_shares
    ADD CONSTRAINT resource_shares_resource_type_check
    CHECK (resource_type IN (
        'workflow',
        'database',
        'credential',
        'saved_output',
        'workflow_folder',
        'skill'
    ));

CREATE OR REPLACE FUNCTION public.can_access_resource(
    p_user_id uuid,
    p_resource_type text,
    p_resource_id uuid,
    p_org_context uuid,
    p_required_permission text DEFAULT 'view'
)
RETURNS boolean
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_owner_id uuid;
    v_org_id uuid;
    v_is_public boolean := false;
    v_is_system boolean := false;
    v_has_access boolean := false;
BEGIN
    IF p_resource_type = 'workflow' THEN
        SELECT owner_id, organization_id INTO v_owner_id, v_org_id
        FROM public.workflows WHERE id = p_resource_id;
    ELSIF p_resource_type = 'database' THEN
        SELECT owner_id, organization_id INTO v_owner_id, v_org_id
        FROM public.user_tables_metadata WHERE id = p_resource_id;
    ELSIF p_resource_type = 'credential' THEN
        SELECT owner_id, organization_id INTO v_owner_id, v_org_id
        FROM public.credentials WHERE id = p_resource_id;
    ELSIF p_resource_type = 'saved_output' THEN
        SELECT owner_id, organization_id, is_public
        INTO v_owner_id, v_org_id, v_is_public
        FROM public.workflow_saved_output WHERE id = p_resource_id;
    ELSIF p_resource_type = 'skill' THEN
        SELECT owner_id, organization_id, is_system
        INTO v_owner_id, v_org_id, v_is_system
        FROM public.skills WHERE id = p_resource_id;
    ELSE
        RETURN false;
    END IF;

    IF v_owner_id IS NULL AND NOT v_is_system THEN
        RETURN false;
    END IF;

    IF v_owner_id = p_user_id THEN
        RETURN true;
    END IF;

    IF p_resource_type = 'saved_output'
       AND v_is_public
       AND p_required_permission = 'view' THEN
        RETURN true;
    END IF;

    IF p_resource_type = 'skill'
       AND v_is_system
       AND p_required_permission = 'view' THEN
        RETURN true;
    END IF;

    SELECT true INTO v_has_access
    FROM public.resource_shares
    WHERE resource_type = p_resource_type
      AND resource_id = p_resource_id
      AND target_type = 'user'
      AND target_user_id = p_user_id
      AND (p_required_permission = 'view' OR permission = 'edit');

    IF v_has_access THEN
        RETURN true;
    END IF;

    SELECT true INTO v_has_access
    FROM public.resource_shares rs
    JOIN public.organization_members om
      ON om.organization_id = rs.target_org_id
    WHERE rs.resource_type = p_resource_type
      AND rs.resource_id = p_resource_id
      AND rs.target_type = 'organization'
      AND om.user_id = p_user_id
      AND (p_required_permission = 'view' OR rs.permission = 'edit');

    RETURN COALESCE(v_has_access, false);
END;
$$;


-- Preserve organization-owned skills when an account is removed. Personal
-- workspace skills are removed by the organization cascade above this update.
CREATE OR REPLACE FUNCTION public.handle_user_deletion()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
    DELETE FROM public.organizations
    WHERE is_personal_workspace = true
      AND id IN (
          SELECT organization_id
          FROM public.organization_members
          WHERE user_id = OLD.id AND role = 'owner'
      );

    UPDATE public.workflows w
    SET owner_id = (
        SELECT user_id FROM public.organization_members
        WHERE organization_id = w.organization_id AND role = 'owner'
        LIMIT 1
    )
    WHERE w.owner_id = OLD.id AND w.organization_id IS NOT NULL;

    UPDATE public.user_tables_metadata t
    SET owner_id = (
        SELECT user_id FROM public.organization_members
        WHERE organization_id = t.organization_id AND role = 'owner'
        LIMIT 1
    )
    WHERE t.owner_id = OLD.id AND t.organization_id IS NOT NULL;

    UPDATE public.credentials c
    SET owner_id = (
        SELECT user_id FROM public.organization_members
        WHERE organization_id = c.organization_id AND role = 'owner'
        LIMIT 1
    )
    WHERE c.owner_id = OLD.id AND c.organization_id IS NOT NULL;

    UPDATE public.workflow_saved_output s
    SET owner_id = (
        SELECT user_id FROM public.organization_members
        WHERE organization_id = s.organization_id AND role = 'owner'
        LIMIT 1
    )
    WHERE s.owner_id = OLD.id AND s.organization_id IS NOT NULL;

    UPDATE public.skills sk
    SET owner_id = (
        SELECT user_id FROM public.organization_members
        WHERE organization_id = sk.organization_id AND role = 'owner'
        LIMIT 1
    )
    WHERE sk.owner_id = OLD.id AND sk.organization_id IS NOT NULL;

    DELETE FROM public.resource_shares
    WHERE shared_by = OLD.id;

    RETURN OLD;
END;
$$;


-- Keep the onboarding-completed token claim in sync with the durable response
-- row while preserving the base schema's workspace claims.
CREATE OR REPLACE FUNCTION public.custom_access_token_hook(event jsonb)
RETURNS jsonb
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    claims jsonb;
    user_org_id uuid;
    user_org_role text;
    personal_ws_org_id uuid;
    user_onboarding_completed boolean;
BEGIN
    claims := event->'claims';

    SELECT EXISTS (
        SELECT 1
        FROM public.user_onboarding_responses
        WHERE user_id = (event->>'user_id')::uuid
    ) INTO user_onboarding_completed;
    claims := jsonb_set(
        claims,
        '{onboarding_completed}',
        to_jsonb(user_onboarding_completed)
    );

    SELECT o.id INTO personal_ws_org_id
    FROM public.organizations o
    JOIN public.organization_members om ON om.organization_id = o.id
    WHERE om.user_id = (event->>'user_id')::uuid
      AND o.is_personal_workspace = true
    LIMIT 1;

    IF personal_ws_org_id IS NOT NULL THEN
        claims := jsonb_set(
            claims,
            '{personal_workspace_org_id}',
            to_jsonb(personal_ws_org_id::text)
        );
    END IF;

    SELECT om.organization_id, om.role
    INTO user_org_id, user_org_role
    FROM public.organization_members om
    WHERE om.user_id = (event->>'user_id')::uuid
    ORDER BY om.is_primary DESC, om.created_at ASC
    LIMIT 1;

    IF user_org_id IS NOT NULL THEN
        claims := jsonb_set(
            claims,
            '{organization_id}',
            to_jsonb(user_org_id::text)
        );
        claims := jsonb_set(
            claims,
            '{organization_role}',
            to_jsonb(user_org_role)
        );
    END IF;

    event := jsonb_set(event, '{claims}', claims);
    RETURN event;
END;
$$;


-- The capability-backed tables and skills are backend-only. Feedback and
-- onboarding keep the narrow signed-in policies used by their browser flows.
ALTER TABLE public.agent_email_replies ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.builder_input_links ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.shared_run_links ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.skills ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.skill_user_mutes ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.user_feedback ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.user_onboarding_responses ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE
    public.agent_email_replies,
    public.builder_input_links,
    public.shared_run_links,
    public.skills,
    public.skill_user_mutes
FROM anon, authenticated;

GRANT ALL ON TABLE
    public.agent_email_replies,
    public.builder_input_links,
    public.shared_run_links,
    public.skills,
    public.skill_user_mutes,
    public.user_feedback,
    public.user_onboarding_responses
TO service_role;

GRANT SELECT, INSERT ON TABLE public.user_feedback TO authenticated;
GRANT SELECT, INSERT ON TABLE public.user_onboarding_responses TO authenticated;

DROP POLICY IF EXISTS user_feedback_select ON public.user_feedback;
CREATE POLICY user_feedback_select ON public.user_feedback
    FOR SELECT TO authenticated
    USING (auth.uid() = user_id);

DROP POLICY IF EXISTS user_feedback_insert ON public.user_feedback;
CREATE POLICY user_feedback_insert ON public.user_feedback
    FOR INSERT TO authenticated
    WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS user_feedback_service ON public.user_feedback;
CREATE POLICY user_feedback_service ON public.user_feedback
    FOR ALL TO service_role
    USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "Users can view own onboarding"
    ON public.user_onboarding_responses;
CREATE POLICY "Users can view own onboarding"
    ON public.user_onboarding_responses
    FOR SELECT TO authenticated
    USING (user_id = auth.uid());

DROP POLICY IF EXISTS "Users can insert own onboarding"
    ON public.user_onboarding_responses;
CREATE POLICY "Users can insert own onboarding"
    ON public.user_onboarding_responses
    FOR INSERT TO authenticated
    WITH CHECK (user_id = auth.uid());

DROP POLICY IF EXISTS "Service role full access to onboarding"
    ON public.user_onboarding_responses;
CREATE POLICY "Service role full access to onboarding"
    ON public.user_onboarding_responses
    FOR ALL TO service_role
    USING (true) WITH CHECK (true);


-- Columns used by schema-learning in the community execution path.
ALTER TABLE public.workflow_node_output_schemas
    ADD COLUMN IF NOT EXISTS sample_config jsonb;
ALTER TABLE public.workflow_node_output_schemas
    ADD COLUMN IF NOT EXISTS sample_output_clipped jsonb;

-- Every source written by the surviving execution paths must satisfy the
-- database check constraint.
ALTER TABLE public.workflow_executions
    DROP CONSTRAINT IF EXISTS workflow_executions_trigger_source_check;
ALTER TABLE public.workflow_executions
    ADD CONSTRAINT workflow_executions_trigger_source_check
    CHECK (trigger_source IN (
        'manual',
        'webhook',
        'cron',
        'mcp',
        'api',
        'email',
        'agent_turn',
        'shared_agent',
        'builder_event',
        'agent_email_reply',
        'error_handler',
        'graph_event'
    ));
