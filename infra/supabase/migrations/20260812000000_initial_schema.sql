-- NoClick Community initial schema.
-- This migration is the complete schema for a fresh self-hosted installation.

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: public; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA IF NOT EXISTS public;

CREATE SCHEMA IF NOT EXISTS extensions;
CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA extensions;


--
-- Name: accept_organization_invite(text); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.accept_organization_invite(invite_token text) RETURNS jsonb
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public'
    AS $$
DECLARE
    invite_record RECORD;
    current_user_id UUID;
    current_user_email TEXT;
BEGIN
    current_user_id := auth.uid();

    IF current_user_id IS NULL THEN
        RETURN jsonb_build_object('success', false, 'error', 'Not authenticated');
    END IF;

    -- Get user email
    SELECT email INTO current_user_email FROM auth.users WHERE id = current_user_id;

    -- Find valid invite
    SELECT * INTO invite_record
    FROM public.organization_invites
    WHERE token = invite_token
    AND accepted_at IS NULL
    AND expires_at > NOW();

    IF invite_record IS NULL THEN
        RETURN jsonb_build_object('success', false, 'error', 'Invalid or expired invite');
    END IF;

    -- Verify email matches (case-insensitive)
    IF LOWER(invite_record.email) != LOWER(current_user_email) THEN
        RETURN jsonb_build_object('success', false, 'error', 'This invite was sent to a different email address');
    END IF;

    -- Check if already a member
    IF EXISTS (SELECT 1 FROM public.organization_members WHERE organization_id = invite_record.organization_id AND user_id = current_user_id) THEN
        RETURN jsonb_build_object('success', false, 'error', 'You are already a member of this organization');
    END IF;

    -- Add as member
    INSERT INTO public.organization_members (organization_id, user_id, role, joined_via, invited_by, invited_at)
    VALUES (invite_record.organization_id, current_user_id, invite_record.role, 'invite', invite_record.invited_by, invite_record.created_at);

    -- Mark invite as accepted
    UPDATE public.organization_invites SET accepted_at = NOW() WHERE id = invite_record.id;

    RETURN jsonb_build_object('success', true, 'organization_id', invite_record.organization_id);
END;
$$;


--
-- Name: bump_token_version(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.bump_token_version() RETURNS trigger
    LANGUAGE plpgsql
    AS $_$
DECLARE
    blob_col text := TG_ARGV[0];
    old_blob text;
    new_blob text;
BEGIN
    EXECUTE format('SELECT ($1).%I::text', blob_col) INTO old_blob USING OLD;
    EXECUTE format('SELECT ($1).%I::text', blob_col) INTO new_blob USING NEW;
    IF new_blob IS DISTINCT FROM old_blob AND NEW.token_version = OLD.token_version THEN
        NEW.token_version := OLD.token_version + 1;
    END IF;
    RETURN NEW;
END
$_$;


--
-- Name: bump_workflow_graph_version(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.bump_workflow_graph_version() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    IF NEW.workflow IS DISTINCT FROM OLD.workflow
       AND NEW.graph_version = OLD.graph_version THEN
        NEW.graph_version := OLD.graph_version + 1;
    END IF;
    RETURN NEW;
END
$$;


--
-- Name: can_access_folder(uuid, uuid); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.can_access_folder(p_user_id uuid, p_folder_id uuid) RETURNS boolean
    LANGUAGE plpgsql STABLE
    AS $$
DECLARE
    v_folder_owner_id UUID;
    v_folder_org_id UUID;
    v_folder_path TEXT;
BEGIN
    -- Get folder details
    SELECT owner_id, organization_id, path
    INTO v_folder_owner_id, v_folder_org_id, v_folder_path
    FROM public.workflow_folders
    WHERE id = p_folder_id;

    IF NOT FOUND THEN
        RETURN FALSE;
    END IF;

    -- Owner always has access
    IF v_folder_owner_id = p_user_id THEN
        RETURN TRUE;
    END IF;

    -- All org members can access any org folder (read-only by default)
    IF v_folder_org_id IS NOT NULL THEN
        IF EXISTS (
            SELECT 1 FROM public.organization_members
            WHERE organization_id = v_folder_org_id
            AND user_id = p_user_id
        ) THEN
            RETURN TRUE;
        END IF;
    END IF;

    -- Direct user share on this exact folder
    IF EXISTS (
        SELECT 1 FROM public.resource_shares
        WHERE resource_type = 'workflow_folder'
        AND resource_id = p_folder_id
        AND target_type = 'user'
        AND target_user_id = p_user_id
    ) THEN
        RETURN TRUE;
    END IF;

    -- Ancestor folder share: check if any ancestor folder in the path is shared with user
    -- Uses materialized path: if folder path is /a/b/c/, check shares on folders a, b, c
    IF EXISTS (
        SELECT 1
        FROM public.workflow_folders f
        JOIN public.resource_shares rs
            ON rs.resource_type = 'workflow_folder'
            AND rs.resource_id = f.id
            AND rs.target_type = 'user'
            AND rs.target_user_id = p_user_id
        WHERE v_folder_path LIKE f.path || '%'
          AND f.id != p_folder_id  -- exclude self (already checked above)
    ) THEN
        RETURN TRUE;
    END IF;

    -- Org-wide folder share (folder or ancestor shared with an org the user belongs to)
    IF EXISTS (
        SELECT 1
        FROM public.workflow_folders f
        JOIN public.resource_shares rs
            ON rs.resource_type = 'workflow_folder'
            AND rs.resource_id = f.id
            AND rs.target_type = 'organization'
        JOIN public.organization_members om
            ON om.organization_id = rs.target_org_id
            AND om.user_id = p_user_id
        WHERE v_folder_path LIKE f.path || '%'
    ) THEN
        RETURN TRUE;
    END IF;

    RETURN FALSE;
END;
$$;


--
-- Name: can_access_resource(uuid, text, uuid, uuid, text); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.can_access_resource(p_user_id uuid, p_resource_type text, p_resource_id uuid, p_org_context uuid, p_required_permission text DEFAULT 'view'::text) RETURNS boolean
    LANGUAGE plpgsql STABLE SECURITY DEFINER
    AS $$
DECLARE
    v_owner_id UUID;
    v_org_id UUID;
    v_is_public BOOLEAN := false;
    v_has_access BOOLEAN := false;
BEGIN
    -- Get resource owner and organization
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
        SELECT owner_id, organization_id, is_public INTO v_owner_id, v_org_id, v_is_public
        FROM public.workflow_saved_output WHERE id = p_resource_id;
    ELSE
        RETURN false;
    END IF;

    -- Resource not found.
    IF v_owner_id IS NULL THEN
        RETURN false;
    END IF;

    -- Owner always has full access.
    IF v_owner_id = p_user_id THEN
        RETURN true;
    END IF;

    -- saved_output: public outputs are view-only for everyone.
    IF p_resource_type = 'saved_output' AND v_is_public AND p_required_permission = 'view' THEN
        RETURN true;
    END IF;

    -- Direct user share.
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

    -- Org share (only if user is a member of the target org).
    SELECT true INTO v_has_access
    FROM public.resource_shares rs
    JOIN public.organization_members om ON om.organization_id = rs.target_org_id
    WHERE rs.resource_type = p_resource_type
      AND rs.resource_id = p_resource_id
      AND rs.target_type = 'organization'
      AND om.user_id = p_user_id
      AND (p_required_permission = 'view' OR rs.permission = 'edit');

    RETURN COALESCE(v_has_access, false);
END;
$$;


--
-- Name: can_access_workflow_with_folders(uuid, uuid); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.can_access_workflow_with_folders(p_user_id uuid, p_workflow_id uuid) RETURNS TABLE(has_access boolean, permission text, source text)
    LANGUAGE plpgsql STABLE
    AS $$
DECLARE
    v_workflow_owner_id UUID;
    v_workflow_org_id UUID;
    v_workflow_folder_id UUID;
    v_folder_path TEXT;
    v_direct_permission TEXT;
    v_folder_permission TEXT;
    v_org_permission TEXT;
BEGIN
    -- Get workflow details
    SELECT w.owner_id, w.organization_id, w.folder_id
    INTO v_workflow_owner_id, v_workflow_org_id, v_workflow_folder_id
    FROM public.workflows w
    WHERE w.id = p_workflow_id;

    IF NOT FOUND THEN
        RETURN QUERY SELECT FALSE, 'none'::TEXT, 'not_found'::TEXT;
        RETURN;
    END IF;

    -- 1. OWNER CHECK (highest priority)
    IF v_workflow_owner_id = p_user_id THEN
        RETURN QUERY SELECT TRUE, 'owner'::TEXT, 'owner'::TEXT;
        RETURN;
    END IF;

    -- 2. DIRECT WORKFLOW SHARE (second priority)
    SELECT rs.permission INTO v_direct_permission
    FROM public.resource_shares rs
    WHERE rs.resource_type = 'workflow'
        AND rs.resource_id = p_workflow_id
        AND rs.target_type = 'user'
        AND rs.target_user_id = p_user_id;

    IF FOUND THEN
        RETURN QUERY SELECT TRUE, v_direct_permission, 'direct_share'::TEXT;
        RETURN;
    END IF;

    -- 3. FOLDER INHERITANCE (third priority - check all ancestor folders)
    IF v_workflow_folder_id IS NOT NULL THEN
        -- Get folder path
        SELECT f.path INTO v_folder_path
        FROM public.workflow_folders f
        WHERE f.id = v_workflow_folder_id;

        -- Check shares on current folder and all ancestors (ordered by depth DESC = closest first)
        SELECT rs.permission INTO v_folder_permission
        FROM public.workflow_folders f
        JOIN public.resource_shares rs
            ON rs.resource_type = 'workflow_folder'
            AND rs.resource_id = f.id
            AND rs.target_type = 'user'
            AND rs.target_user_id = p_user_id
        WHERE v_folder_path LIKE f.path || '%'  -- Current folder or any ancestor
        ORDER BY f.depth DESC  -- Closest ancestor wins
        LIMIT 1;

        IF FOUND THEN
            RETURN QUERY SELECT TRUE, v_folder_permission, 'folder_share'::TEXT;
            RETURN;
        END IF;
    END IF;

    -- 4. ORGANIZATION SHARE (lowest priority)
    IF v_workflow_org_id IS NOT NULL THEN
        SELECT rs.permission INTO v_org_permission
        FROM public.resource_shares rs
        JOIN public.organization_members om
            ON om.organization_id = rs.target_org_id
            AND om.user_id = p_user_id
        WHERE rs.resource_type = 'workflow'
            AND rs.resource_id = p_workflow_id
            AND rs.target_type = 'organization';

        IF FOUND THEN
            RETURN QUERY SELECT TRUE, v_org_permission, 'org_share'::TEXT;
            RETURN;
        END IF;
    END IF;

    -- 5. NO ACCESS
    RETURN QUERY SELECT FALSE, 'none'::TEXT, 'none'::TEXT;
END;
$$;


--
-- Name: convert_pending_shares(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.convert_pending_shares() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    AS $$
BEGIN
    -- Convert pending email shares to user_id shares
    UPDATE public.resource_shares
    SET target_user_id = NEW.id,
        target_email = NULL
    WHERE target_email = NEW.email
      AND target_type = 'user'
      AND target_user_id IS NULL;

    RETURN NEW;
END;
$$;


--
-- Name: user_organization_ids(); Type: FUNCTION; Schema: public; Owner: -
--
-- The caller's organizations, and the subset they administer.
--
-- These exist so the policies ON organization_members can ask "which orgs is
-- this person in?" without reading organization_members through its own policy,
-- which is a cycle Postgres stops with `42P17 infinite recursion detected`. That
-- error took out every policy that reads the table, directly or through another
-- one — organizations, organization_invites, workflow_folders and
-- resource_shares included.
--
-- SECURITY DEFINER is the mechanism: the body runs as the owner, so the read
-- inside is not itself policy-checked. It stays safe because the function takes
-- no arguments and answers only about auth.uid() — there is no other question it
-- can be asked.
--

CREATE FUNCTION public.user_organization_ids() RETURNS SETOF uuid
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'public'
    AS $$
    SELECT organization_id FROM public.organization_members
    WHERE user_id = auth.uid()
$$;


--
-- Name: user_admin_organization_ids(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.user_admin_organization_ids() RETURNS SETOF uuid
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'public'
    AS $$
    SELECT organization_id FROM public.organization_members
    WHERE user_id = auth.uid()
      AND role = ANY (ARRAY['owner'::text, 'admin'::text])
$$;


--
-- Name: organization_has_members(uuid); Type: FUNCTION; Schema: public; Owner: -
--
-- Asked by the policy that lets someone claim an organization nobody is in yet.
-- SECURITY DEFINER for the same reason as the two above: the question is about
-- `organization_members`, and a policy ON that table cannot read it directly.
--
-- This one takes an argument, which the other two deliberately do not. That is
-- safe here because of WHAT it answers: whether an organization has any members
-- at all, about an id the caller already holds. It exposes no membership, no
-- identity, and nothing that differs between two people asking.
--

CREATE FUNCTION public.organization_has_members(org_id uuid) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'public'
    AS $$
    SELECT EXISTS (
        SELECT 1 FROM public.organization_members WHERE organization_id = org_id
    )
$$;


REVOKE ALL ON FUNCTION public.user_organization_ids() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.user_admin_organization_ids() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.user_organization_ids() TO authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.user_admin_organization_ids() TO authenticated, service_role;
REVOKE ALL ON FUNCTION public.organization_has_members(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.organization_has_members(uuid) TO authenticated, service_role;


--
-- Name: custom_access_token_hook(jsonb); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.custom_access_token_hook(event jsonb) RETURNS jsonb
    LANGUAGE plpgsql STABLE SECURITY DEFINER
    SET search_path TO 'public'
    AS $$
DECLARE
  claims jsonb;
  user_org_id uuid;
  user_org_role text;
  personal_ws_org_id uuid;
BEGIN
  claims := event->'claims';

  SELECT o.id INTO personal_ws_org_id
  FROM public.organizations o
  JOIN public.organization_members om ON om.organization_id = o.id
  WHERE om.user_id = (event->>'user_id')::uuid
    AND o.is_personal_workspace = true
  LIMIT 1;

  IF personal_ws_org_id IS NOT NULL THEN
    claims := jsonb_set(claims, '{personal_workspace_org_id}', to_jsonb(personal_ws_org_id::text));
  END IF;

  SELECT om.organization_id, om.role
  INTO user_org_id, user_org_role
  FROM public.organization_members om
  WHERE om.user_id = (event->>'user_id')::uuid
  ORDER BY om.is_primary DESC, om.created_at ASC
  LIMIT 1;

  IF user_org_id IS NOT NULL THEN
    claims := jsonb_set(claims, '{organization_id}', to_jsonb(user_org_id::text));
    claims := jsonb_set(claims, '{organization_role}', to_jsonb(user_org_role));
  END IF;

  event := jsonb_set(event, '{claims}', claims);
  RETURN event;
END;
$$;


--
-- Name: handle_new_user_registration(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.handle_new_user_registration() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public'
    AS $$
DECLARE
  new_org_id uuid;
  user_name text;
BEGIN
  new_org_id := gen_random_uuid();
  user_name := COALESCE(
    NEW.raw_user_meta_data->>'username',
    split_part(NEW.email, '@', 1),
    'User'
  );

  INSERT INTO public.organizations (
    id, name, slug, is_personal_workspace
  ) VALUES (
    new_org_id,
    user_name || '''s Workspace',
    'personal-' || NEW.id::text,
    true
  )
  ON CONFLICT DO NOTHING;

  INSERT INTO public.organization_members (
    organization_id, user_id, role, joined_via, is_primary
  ) VALUES (
    new_org_id, NEW.id, 'owner', 'creator', true
  )
  ON CONFLICT DO NOTHING;

  RETURN NEW;
END;
$$;


--
-- Name: handle_sso_user_login(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.handle_sso_user_login() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public'
    AS $$
DECLARE
  sso_provider_uuid text;
  org_id uuid;
BEGIN
  IF NEW.provider NOT LIKE 'sso:%' THEN
    RETURN NEW;
  END IF;

  sso_provider_uuid := replace(NEW.provider, 'sso:', '');
  SELECT id INTO org_id
  FROM public.organizations
  WHERE sso_provider_id = sso_provider_uuid
    AND sso_enabled = true;

  IF org_id IS NULL OR EXISTS (
    SELECT 1 FROM public.organization_members
    WHERE organization_id = org_id AND user_id = NEW.user_id
  ) THEN
    RETURN NEW;
  END IF;

  UPDATE public.organization_members
  SET is_primary = false
  WHERE user_id = NEW.user_id;

  INSERT INTO public.organization_members (
    organization_id, user_id, role, joined_via, is_primary
  ) VALUES (
    org_id, NEW.user_id, 'member', 'sso', true
  );

  RETURN NEW;
END;
$$;


--
-- Name: handle_user_deletion(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.handle_user_deletion() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    AS $$
BEGIN
    -- Delete the personal workspace organization; foreign keys cascade to
    -- organization-scoped resources.
    DELETE FROM public.organizations
    WHERE is_personal_workspace = true
    AND id IN (
      SELECT organization_id FROM public.organization_members
      WHERE user_id = OLD.id AND role = 'owner'
    );

    -- Transfer org workflows to the org owner (for non-personal orgs).
    UPDATE public.workflows w
    SET owner_id = (
        SELECT user_id FROM public.organization_members
        WHERE organization_id = w.organization_id AND role = 'owner'
        LIMIT 1
    )
    WHERE w.owner_id = OLD.id AND w.organization_id IS NOT NULL;

    -- Transfer org databases.
    UPDATE public.user_tables_metadata t
    SET owner_id = (
        SELECT user_id FROM public.organization_members
        WHERE organization_id = t.organization_id AND role = 'owner'
        LIMIT 1
    )
    WHERE t.owner_id = OLD.id AND t.organization_id IS NOT NULL;

    -- Transfer org credentials.
    UPDATE public.credentials c
    SET owner_id = (
        SELECT user_id FROM public.organization_members
        WHERE organization_id = c.organization_id AND role = 'owner'
        LIMIT 1
    )
    WHERE c.owner_id = OLD.id AND c.organization_id IS NOT NULL;

    -- Transfer org saved outputs.
    UPDATE public.workflow_saved_output s
    SET owner_id = (
        SELECT user_id FROM public.organization_members
        WHERE organization_id = s.organization_id AND role = 'owner'
        LIMIT 1
    )
    WHERE s.owner_id = OLD.id AND s.organization_id IS NOT NULL;

    -- Delete shares created by this user.
    -- (target_user_id rows in resource_shares are handled by ON DELETE CASCADE.)
    DELETE FROM public.resource_shares
    WHERE shared_by = OLD.id;

    RETURN OLD;
END;
$$;


--
-- Name: init_user_onboarding_completion(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.init_user_onboarding_completion() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    AS $$
BEGIN
    INSERT INTO public.user_onboarding_completion (user_id)
    VALUES (NEW.id)
    ON CONFLICT (user_id) DO NOTHING;
    RETURN NEW;
END;
$$;


--
-- Name: lookup_invite_by_token(text); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.lookup_invite_by_token(invite_token text) RETURNS TABLE(id uuid, organization_id uuid, organization_name text, email text, role text, expires_at timestamp with time zone)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public'
    AS $$
BEGIN
    RETURN QUERY
    SELECT
        i.id,
        i.organization_id,
        o.name as organization_name,
        i.email,
        i.role,
        i.expires_at
    FROM public.organization_invites i
    JOIN public.organizations o ON o.id = i.organization_id
    WHERE i.token = invite_token
    AND i.accepted_at IS NULL
    AND i.expires_at > NOW();
END;
$$;


--
-- Name: lookup_sso_organization(text); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.lookup_sso_organization(org_slug text) RETURNS TABLE(id uuid, name text, sso_provider_id text, sso_enabled boolean)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public'
    AS $$
BEGIN
    RETURN QUERY
    SELECT o.id, o.name, o.sso_provider_id, o.sso_enabled
    FROM public.organizations o
    WHERE o.slug = org_slug AND o.sso_enabled = true;
END;
$$;


--
-- Name: prevent_circular_folder_reference(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.prevent_circular_folder_reference() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_ancestor_id UUID;
    v_max_iterations INTEGER := 20; -- Safety limit
    v_iterations INTEGER := 0;
BEGIN
    -- Skip check if no parent
    IF NEW.parent_folder_id IS NULL THEN
        RETURN NEW;
    END IF;

    -- Check if new parent would create a cycle
    v_ancestor_id := NEW.parent_folder_id;

    WHILE v_ancestor_id IS NOT NULL AND v_iterations < v_max_iterations LOOP
        -- If we find the current folder in its own ancestry, that's a cycle
        IF v_ancestor_id = NEW.id THEN
            RAISE EXCEPTION 'Circular folder reference detected: folder cannot be its own ancestor';
        END IF;

        -- Move up the tree
        SELECT parent_folder_id INTO v_ancestor_id
        FROM public.workflow_folders
        WHERE id = v_ancestor_id;

        v_iterations := v_iterations + 1;
    END LOOP;

    -- Safety check: if we hit max iterations, something is wrong
    IF v_iterations >= v_max_iterations THEN
        RAISE EXCEPTION 'Maximum folder nesting depth exceeded or circular reference detected';
    END IF;

    RETURN NEW;
END;
$$;


--
-- Name: slack_installations_touch_updated_at(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.slack_installations_touch_updated_at() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END
$$;


--
-- Name: update_folder_path_and_depth(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.update_folder_path_and_depth() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_parent_path TEXT;
    v_parent_depth INTEGER;
BEGIN
    -- If no parent, this is a root folder
    IF NEW.parent_folder_id IS NULL THEN
        -- Root folders get path like /uuid/ (not just /)
        NEW.path := '/' || NEW.id::TEXT || '/';
        NEW.depth := 0;
    ELSE
        -- Get parent's path and depth
        SELECT path, depth INTO v_parent_path, v_parent_depth
        FROM public.workflow_folders
        WHERE id = NEW.parent_folder_id;

        IF NOT FOUND THEN
            RAISE EXCEPTION 'Parent folder not found: %', NEW.parent_folder_id;
        END IF;

        -- Build new path: parent_path + folder_id + '/'
        NEW.path := v_parent_path || NEW.id::TEXT || '/';
        NEW.depth := v_parent_depth + 1;
    END IF;

    RETURN NEW;
END;
$$;


--
-- Name: update_onboarding_completion_updated_at(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.update_onboarding_completion_updated_at() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;


--
-- Name: update_updated_at_column(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.update_updated_at_column() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;


--
-- Name: update_workflow_folder_updated_at(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.update_workflow_folder_updated_at() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    NEW.updated_at := NOW();
    RETURN NEW;
END;
$$;


--
-- Name: workflows_touch_updated_at_content_only(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.workflows_touch_updated_at_content_only() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    IF NEW.name IS DISTINCT FROM OLD.name
       OR NEW.description IS DISTINCT FROM OLD.description
       OR NEW.owner_id IS DISTINCT FROM OLD.owner_id
       OR NEW.organization_id IS DISTINCT FROM OLD.organization_id
       OR NEW.folder_id IS DISTINCT FROM OLD.folder_id
       OR NEW.deleted_at IS DISTINCT FROM OLD.deleted_at
       OR NEW.permissions IS DISTINCT FROM OLD.permissions
       OR NEW.settings IS DISTINCT FROM OLD.settings
       OR NEW.workflow IS DISTINCT FROM OLD.workflow THEN
        NEW.updated_at := NOW();
    ELSE
        NEW.updated_at := OLD.updated_at;
    END IF;
    RETURN NEW;
END
$$;


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: activity_logs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.activity_logs (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    workflow_id uuid NOT NULL,
    execution_id uuid NOT NULL,
    node_id text NOT NULL,
    user_id uuid NOT NULL,
    organization_id uuid,
    message text NOT NULL,
    level text DEFAULT 'info'::text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT activity_logs_level_check CHECK ((level = ANY (ARRAY['info'::text, 'success'::text, 'warning'::text, 'error'::text])))
);


--
-- Name: api_keys; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.api_keys (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid NOT NULL,
    key_hash text NOT NULL,
    key_prefix text NOT NULL,
    name text DEFAULT ''::text NOT NULL,
    workflow_id uuid,
    permissions text[] DEFAULT '{}'::text[] NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    last_used_at timestamp with time zone,
    expires_at timestamp with time zone,
    revoked_at timestamp with time zone
);


--
-- Name: approval_requests; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.approval_requests (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    workflow_id uuid NOT NULL,
    execution_id uuid NOT NULL,
    node_id text NOT NULL,
    user_id uuid NOT NULL,
    organization_id uuid,
    title text,
    content text NOT NULL,
    status text DEFAULT 'pending'::text NOT NULL,
    decided_by uuid,
    decided_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT approval_requests_status_check CHECK ((status = ANY (ARRAY['pending'::text, 'approved'::text, 'rejected'::text])))
);


--
-- Name: cas_blobs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.cas_blobs (
    hash text NOT NULL,
    size_bytes integer NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    orphaned_at timestamp with time zone
);


--
-- Name: cas_manifests; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.cas_manifests (
    workflow_id uuid NOT NULL,
    execution_id uuid NOT NULL,
    node_id text NOT NULL,
    manifest jsonb,
    last_run_status text,
    last_run_error text,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: cas_refs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.cas_refs (
    workflow_id uuid NOT NULL,
    execution_id uuid NOT NULL,
    node_id text NOT NULL,
    chunk_hash text NOT NULL
);


--
-- Name: cas_storage_stats; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.cas_storage_stats (
    workflow_id uuid NOT NULL,
    physical_bytes bigint DEFAULT 0 NOT NULL,
    logical_bytes bigint DEFAULT 0 NOT NULL,
    graph_bytes bigint DEFAULT 0 NOT NULL,
    output_bytes bigint DEFAULT 0 NOT NULL,
    manifest_bytes bigint DEFAULT 0 NOT NULL,
    execution_count integer DEFAULT 0 NOT NULL,
    distinct_graphs integer DEFAULT 0 NOT NULL,
    chunk_count integer DEFAULT 0 NOT NULL,
    computed_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: conversations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.conversations (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    conversation_id text NOT NULL,
    user_id uuid NOT NULL,
    title text,
    preview text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    last_activity timestamp with time zone DEFAULT now() NOT NULL,
    deleted_at timestamp with time zone,
    app_id text,
    app_name text,
    events jsonb DEFAULT '[]'::jsonb NOT NULL,
    metadata jsonb DEFAULT '{}'::jsonb,
    workflow_id text,
    node_id text,
    agent_state text,
    pending_ask jsonb,
    total_cost numeric(12,6) DEFAULT 0 NOT NULL,
    total_tokens bigint DEFAULT 0 NOT NULL,
    turn_count integer DEFAULT 0 NOT NULL,
    agent_model text
);


--
-- Name: credential_requests; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.credential_requests (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    requester_id uuid NOT NULL,
    target_email text NOT NULL,
    credential_type text NOT NULL,
    message text,
    token text DEFAULT encode(extensions.gen_random_bytes(32), 'hex'::text) NOT NULL,
    status text DEFAULT 'pending'::text NOT NULL,
    credential_id uuid,
    expires_at timestamp with time zone DEFAULT (now() + '7 days'::interval) NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    fulfilled_at timestamp with time zone,
    provision_attempts integer DEFAULT 0 NOT NULL,
    CONSTRAINT credential_requests_status_check CHECK ((status = ANY (ARRAY['pending'::text, 'fulfilled'::text, 'expired'::text, 'cancelled'::text])))
);


--
-- Name: credentials; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.credentials (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    owner_id uuid NOT NULL,
    credential_type text NOT NULL,
    credential text NOT NULL,
    metadata jsonb DEFAULT '{}'::jsonb,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    name text NOT NULL,
    organization_id uuid,
    revoked_at timestamp with time zone,
    revoked_reason text,
    token_version integer DEFAULT 1 NOT NULL
);


--
-- Name: dataset_rows; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dataset_rows (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    resource_id uuid NOT NULL,
    row_index integer NOT NULL,
    data jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: email_reservations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.email_reservations (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid NOT NULL,
    workflow_id uuid NOT NULL,
    node_id text NOT NULL,
    local_part text NOT NULL,
    domain text NOT NULL,
    is_active boolean DEFAULT true,
    last_received_at timestamp with time zone,
    receive_count integer DEFAULT 0,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    CONSTRAINT email_reservations_local_part_format CHECK (((local_part ~ '^[a-z0-9]+([._-][a-z0-9]+)*$'::text) AND (length(local_part) <= 64)))
);


--
-- Name: instance_oauth_apps; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.instance_oauth_apps (
    provider text NOT NULL,
    client_id text NOT NULL,
    client_secret_encrypted text,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_by uuid
);


--
-- Name: invite_redemptions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.invite_redemptions (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    invite_token text NOT NULL,
    workflow_id uuid,
    inviter_id uuid,
    redeemer_id uuid NOT NULL,
    redeemed_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: local_cron_schedules; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.local_cron_schedules (
    id uuid NOT NULL,
    user_id text NOT NULL,
    workflow_id text NOT NULL,
    node_id text NOT NULL,
    cron_expression text NOT NULL,
    webhook_url text NOT NULL,
    payload jsonb,
    timezone text DEFAULT 'UTC'::text NOT NULL,
    enabled boolean DEFAULT true NOT NULL,
    run_once boolean DEFAULT false NOT NULL,
    max_attempts integer DEFAULT 3 NOT NULL,
    next_run timestamp with time zone NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: mcp_server_links; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.mcp_server_links (
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
-- Name: organization_invites; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.organization_invites (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    organization_id uuid NOT NULL,
    email text NOT NULL,
    role text DEFAULT 'member'::text NOT NULL,
    invited_by uuid NOT NULL,
    token text DEFAULT encode(extensions.gen_random_bytes(32), 'hex'::text) NOT NULL,
    expires_at timestamp with time zone DEFAULT (now() + '7 days'::interval) NOT NULL,
    accepted_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now(),
    CONSTRAINT organization_invites_role_check CHECK ((role = ANY (ARRAY['admin'::text, 'member'::text])))
);


--
-- Name: organization_members; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.organization_members (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    organization_id uuid NOT NULL,
    user_id uuid NOT NULL,
    role text DEFAULT 'member'::text NOT NULL,
    joined_via text DEFAULT 'invite'::text NOT NULL,
    is_primary boolean DEFAULT false,
    invited_by uuid,
    invited_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    CONSTRAINT organization_members_joined_via_check CHECK ((joined_via = ANY (ARRAY['sso'::text, 'invite'::text, 'creator'::text]))),
    CONSTRAINT organization_members_role_check CHECK ((role = ANY (ARRAY['owner'::text, 'admin'::text, 'member'::text])))
);


--
-- Name: organizations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.organizations (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    name text NOT NULL,
    slug text NOT NULL,
    icon_url text,
    sso_provider_id text,
    sso_domain text,
    sso_metadata_url text,
    sso_enabled boolean DEFAULT false,
    settings jsonb DEFAULT '{}'::jsonb,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    is_personal_workspace boolean DEFAULT false NOT NULL,
    CONSTRAINT organizations_slug_format CHECK (((slug ~ '^[a-z0-9][a-z0-9-]*[a-z0-9]$'::text) OR (slug ~ '^[a-z0-9]$'::text)))
);


--
-- Name: resource_forks; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.resource_forks (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    resource_type text NOT NULL,
    source_id uuid NOT NULL,
    forked_id uuid NOT NULL,
    forked_by uuid NOT NULL,
    forked_at timestamp with time zone DEFAULT now(),
    CONSTRAINT resource_forks_resource_type_check CHECK ((resource_type = ANY (ARRAY['workflow'::text, 'database'::text])))
);


--
-- Name: resource_shares; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.resource_shares (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    resource_type text NOT NULL,
    resource_id uuid NOT NULL,
    target_type text NOT NULL,
    target_org_id uuid,
    target_user_id uuid,
    target_email text,
    permission text DEFAULT 'view'::text NOT NULL,
    shared_by uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    target_folder_id uuid,
    CONSTRAINT resource_shares_permission_check CHECK ((permission = ANY (ARRAY['view'::text, 'edit'::text]))),
    CONSTRAINT resource_shares_resource_type_check CHECK ((resource_type = ANY (ARRAY['workflow'::text, 'database'::text, 'credential'::text, 'saved_output'::text, 'workflow_folder'::text]))),
    CONSTRAINT resource_shares_target_type_check CHECK ((target_type = ANY (ARRAY['organization'::text, 'user'::text, 'public'::text]))),
    CONSTRAINT share_target_check CHECK ((((target_type = 'organization'::text) AND (target_org_id IS NOT NULL) AND (target_user_id IS NULL) AND (target_email IS NULL)) OR ((target_type = 'user'::text) AND (target_org_id IS NULL) AND ((target_user_id IS NOT NULL) OR (target_email IS NOT NULL))) OR ((target_type = 'public'::text) AND (target_org_id IS NULL) AND (target_user_id IS NULL) AND (target_email IS NULL))))
);


--
-- Name: shared_agent_links; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.shared_agent_links (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid NOT NULL,
    workflow_id uuid NOT NULL,
    node_id text NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    last_used_at timestamp with time zone,
    turn_count integer DEFAULT 0 NOT NULL
);


--
-- Name: slack_installations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.slack_installations (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    team_id text NOT NULL,
    app_id text DEFAULT ''::text NOT NULL,
    client_id text DEFAULT ''::text NOT NULL,
    installation text NOT NULL,
    token_version integer DEFAULT 1 NOT NULL,
    revoked_at timestamp with time zone,
    revoked_reason text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: tool_call_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.tool_call_events (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid NOT NULL,
    workflow_id uuid,
    execution_id uuid,
    conversation_id text,
    agent_node_id text,
    tool_name text NOT NULL,
    tool_type text NOT NULL,
    provider_node_id text,
    operation text,
    credential_id uuid,
    arguments jsonb,
    result_status text NOT NULL,
    error text,
    result_preview text,
    duration_ms integer,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    model text
);


--
-- Name: user_notification_preferences; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.user_notification_preferences (
    user_id uuid NOT NULL,
    prefs jsonb DEFAULT '{}'::jsonb NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: user_notifications; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.user_notifications (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid NOT NULL,
    category text NOT NULL,
    dedupe_key text,
    title text NOT NULL,
    body text DEFAULT ''::text NOT NULL,
    cta_text text,
    cta_url text,
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    email_sent boolean DEFAULT false NOT NULL,
    suppressed_count integer DEFAULT 0 NOT NULL,
    last_seen_at timestamp with time zone DEFAULT now() NOT NULL,
    read_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: user_onboarding_completion; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.user_onboarding_completion (
    user_id uuid NOT NULL,
    data jsonb DEFAULT '{"has_seen_welcome": false, "workflow_checklist": {"drag_node": false, "configure_node": false, "create_workflow": false, "open_flow_helper": false, "open_sidebar_chat": false}, "checklist_dismissed": false}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: user_tables_metadata; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.user_tables_metadata (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    owner_id uuid NOT NULL,
    credential_id uuid,
    source text DEFAULT 'managed'::text,
    virtual_table_name text NOT NULL,
    title text NOT NULL,
    description text DEFAULT ''::text,
    permissions jsonb DEFAULT '{"public": false, "shared_with": []}'::jsonb,
    schema_definition jsonb NOT NULL,
    display_metadata jsonb DEFAULT '{}'::jsonb,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    organization_id uuid,
    CONSTRAINT check_source_credential CHECK ((((source = 'managed'::text) AND (credential_id IS NULL)) OR ((source <> 'managed'::text) AND (credential_id IS NOT NULL)))),
    CONSTRAINT check_valid_source CHECK ((source = ANY (ARRAY['managed'::text, 'external'::text])))
);


--
-- Name: webhook_channels; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.webhook_channels (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    webhook_id uuid NOT NULL,
    user_id uuid NOT NULL,
    workflow_id uuid NOT NULL,
    node_id text NOT NULL,
    provider text NOT NULL,
    credential_id uuid,
    channel_id text,
    resource_id text,
    watched_resource text,
    channel_token text,
    expires_at timestamp with time zone NOT NULL,
    renew_after timestamp with time zone NOT NULL,
    last_renewed_at timestamp with time zone,
    renewal_attempts integer DEFAULT 0 NOT NULL,
    last_renewal_error text,
    claimed_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: webhook_subscriptions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.webhook_subscriptions (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    provider text NOT NULL,
    tenant_id text NOT NULL,
    event_type text NOT NULL,
    user_id uuid NOT NULL,
    workflow_id uuid NOT NULL,
    node_id text NOT NULL,
    credential_id uuid,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    verification_key text
);


--
-- Name: webhooks; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.webhooks (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid NOT NULL,
    workflow_id uuid NOT NULL,
    node_id text NOT NULL,
    name text DEFAULT 'Webhook'::text,
    secret text,
    is_active boolean DEFAULT true,
    last_triggered_at timestamp with time zone,
    trigger_count integer DEFAULT 0,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    organization_id uuid,
    external_webhook_id text,
    registered_operation text,
    registered_credential_id text,
    registered_fingerprint text
);


--
-- Name: workflow_authorized_credentials; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.workflow_authorized_credentials (
    workflow_id uuid NOT NULL,
    credential_id uuid NOT NULL,
    authorized_by uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: workflow_checkpoints; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.workflow_checkpoints (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid NOT NULL,
    workflow_id uuid NOT NULL,
    name text NOT NULL,
    description text DEFAULT ''::text,
    workflow jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: workflow_executions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.workflow_executions (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    workflow_id uuid NOT NULL,
    user_id uuid NOT NULL,
    status text NOT NULL,
    started_at timestamp with time zone DEFAULT now() NOT NULL,
    finished_at timestamp with time zone,
    nodes_executed integer DEFAULT 0,
    error text,
    wake_at timestamp with time zone,
    resume_node_id text,
    external_schedule_id text,
    graph_hash text,
    trigger_source text DEFAULT 'manual'::text NOT NULL,
    CONSTRAINT workflow_executions_status_check CHECK ((status = ANY (ARRAY['running'::text, 'completed'::text, 'error'::text, 'awaiting_approval'::text, 'awaiting_delay'::text]))),
    CONSTRAINT workflow_executions_trigger_source_check CHECK ((trigger_source = ANY (ARRAY['manual'::text, 'webhook'::text, 'cron'::text, 'mcp'::text, 'api'::text, 'email'::text, 'agent_turn'::text, 'shared_agent'::text, 'graph_event'::text, 'error_handler'::text])))
);


--
-- Name: workflow_folders; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.workflow_folders (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    owner_id uuid NOT NULL,
    organization_id uuid,
    name text NOT NULL,
    description text DEFAULT ''::text,
    parent_folder_id uuid,
    path text DEFAULT '/'::text NOT NULL,
    depth integer DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT workflow_folders_max_depth CHECK ((depth <= 10)),
    CONSTRAINT workflow_folders_no_self_reference CHECK ((id <> parent_folder_id)),
    CONSTRAINT workflow_folders_path_format CHECK ((path ~ '^(/[a-f0-9-]+)+/$'::text))
);


--
-- Name: workflow_invite_links; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.workflow_invite_links (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    workflow_id uuid NOT NULL,
    token text NOT NULL,
    permission text DEFAULT 'edit'::text NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    created_by uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    expires_at timestamp with time zone,
    CONSTRAINT workflow_invite_links_permission_check CHECK ((permission = ANY (ARRAY['view'::text, 'edit'::text])))
);


--
-- Name: workflow_node_output_schemas; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.workflow_node_output_schemas (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    node_type text NOT NULL,
    node_operation text NOT NULL,
    output_schema jsonb NOT NULL,
    schema_hash text NOT NULL,
    first_seen_at timestamp with time zone DEFAULT now() NOT NULL,
    last_seen_at timestamp with time zone DEFAULT now() NOT NULL,
    occurrence_count integer DEFAULT 1 NOT NULL,
    suggested_refs jsonb,
    suggestions_updated_at timestamp with time zone
);


--
-- Name: workflow_node_state; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.workflow_node_state (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    workflow_id uuid NOT NULL,
    node_id text NOT NULL,
    state jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    version bigint DEFAULT 0 NOT NULL
);


--
-- Name: workflow_resources; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.workflow_resources (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    owner_id uuid NOT NULL,
    organization_id uuid,
    workflow_id uuid NOT NULL,
    node_id text,
    resource_type text NOT NULL,
    name text NOT NULL,
    mime_type text,
    size_bytes bigint DEFAULT 0,
    storage_ref text,
    metadata jsonb DEFAULT '{}'::jsonb,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    CONSTRAINT workflow_resources_resource_type_check CHECK ((resource_type = ANY (ARRAY['dataset'::text, 'file'::text, 'image'::text, 'video'::text, 'audio'::text, 'document'::text])))
);


--
-- Name: workflow_run_totals; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.workflow_run_totals (
    workflow_id uuid NOT NULL,
    executions_total bigint DEFAULT 0 NOT NULL,
    bytes_reclaimed bigint DEFAULT 0 NOT NULL,
    last_cleanup_at timestamp with time zone
);


--
-- Name: workflow_saved_output; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.workflow_saved_output (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    owner_id uuid NOT NULL,
    organization_id uuid,
    node_type text NOT NULL,
    name text NOT NULL,
    output jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    is_public boolean DEFAULT false
);


--
-- Name: workflows; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.workflows (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    owner_id uuid NOT NULL,
    name text NOT NULL,
    description text DEFAULT ''::text,
    workflow jsonb DEFAULT '{}'::jsonb NOT NULL,
    permissions jsonb DEFAULT '{"public": [], "shared_with": {}}'::jsonb,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    display_metadata jsonb DEFAULT '{}'::jsonb,
    organization_id uuid,
    folder_id uuid,
    deleted_at timestamp with time zone,
    settings jsonb DEFAULT '{}'::jsonb,
    graph_version bigint DEFAULT 1 NOT NULL
);


--
-- Name: activity_logs activity_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.activity_logs
    ADD CONSTRAINT activity_logs_pkey PRIMARY KEY (id);


--
-- Name: api_keys api_keys_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.api_keys
    ADD CONSTRAINT api_keys_pkey PRIMARY KEY (id);


--
-- Name: approval_requests approval_requests_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.approval_requests
    ADD CONSTRAINT approval_requests_pkey PRIMARY KEY (id);


--
-- Name: cas_blobs cas_blobs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cas_blobs
    ADD CONSTRAINT cas_blobs_pkey PRIMARY KEY (hash);


--
-- Name: cas_manifests cas_manifests_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cas_manifests
    ADD CONSTRAINT cas_manifests_pkey PRIMARY KEY (execution_id, node_id);


--
-- Name: cas_refs cas_refs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cas_refs
    ADD CONSTRAINT cas_refs_pkey PRIMARY KEY (execution_id, node_id, chunk_hash);


--
-- Name: cas_storage_stats cas_storage_stats_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cas_storage_stats
    ADD CONSTRAINT cas_storage_stats_pkey PRIMARY KEY (workflow_id);


--
-- Name: conversations conversations_conversation_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.conversations
    ADD CONSTRAINT conversations_conversation_id_key UNIQUE (conversation_id);


--
-- Name: conversations conversations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.conversations
    ADD CONSTRAINT conversations_pkey PRIMARY KEY (id);


--
-- Name: credential_requests credential_requests_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.credential_requests
    ADD CONSTRAINT credential_requests_pkey PRIMARY KEY (id);


--
-- Name: credential_requests credential_requests_token_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.credential_requests
    ADD CONSTRAINT credential_requests_token_key UNIQUE (token);


--
-- Name: credentials credentials_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.credentials
    ADD CONSTRAINT credentials_pkey PRIMARY KEY (id);


--
-- Name: dataset_rows dataset_rows_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dataset_rows
    ADD CONSTRAINT dataset_rows_pkey PRIMARY KEY (id);


--
-- Name: email_reservations email_reservations_address_unique; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.email_reservations
    ADD CONSTRAINT email_reservations_address_unique UNIQUE (domain, local_part);


--
-- Name: email_reservations email_reservations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.email_reservations
    ADD CONSTRAINT email_reservations_pkey PRIMARY KEY (id);


--
-- Name: email_reservations email_reservations_workflow_node_unique; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.email_reservations
    ADD CONSTRAINT email_reservations_workflow_node_unique UNIQUE (workflow_id, node_id);


--
-- Name: instance_oauth_apps instance_oauth_apps_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.instance_oauth_apps
    ADD CONSTRAINT instance_oauth_apps_pkey PRIMARY KEY (provider);


--
-- Name: invite_redemptions invite_redemptions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.invite_redemptions
    ADD CONSTRAINT invite_redemptions_pkey PRIMARY KEY (id);


--
-- Name: local_cron_schedules local_cron_schedules_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.local_cron_schedules
    ADD CONSTRAINT local_cron_schedules_pkey PRIMARY KEY (id);


--
-- Name: mcp_server_links mcp_server_links_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.mcp_server_links
    ADD CONSTRAINT mcp_server_links_pkey PRIMARY KEY (id);


--
-- Name: mcp_server_links mcp_server_links_workflow_id_node_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.mcp_server_links
    ADD CONSTRAINT mcp_server_links_workflow_id_node_id_key UNIQUE (workflow_id, node_id);


--
-- Name: organization_invites organization_invites_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.organization_invites
    ADD CONSTRAINT organization_invites_pkey PRIMARY KEY (id);


--
-- Name: organization_invites organization_invites_token_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.organization_invites
    ADD CONSTRAINT organization_invites_token_key UNIQUE (token);


--
-- Name: organization_members organization_members_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.organization_members
    ADD CONSTRAINT organization_members_pkey PRIMARY KEY (id);


--
-- Name: organizations organizations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.organizations
    ADD CONSTRAINT organizations_pkey PRIMARY KEY (id);


--
-- Name: organizations organizations_slug_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.organizations
    ADD CONSTRAINT organizations_slug_key UNIQUE (slug);


--
-- Name: resource_forks resource_forks_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.resource_forks
    ADD CONSTRAINT resource_forks_pkey PRIMARY KEY (id);


--
-- Name: resource_shares resource_shares_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.resource_shares
    ADD CONSTRAINT resource_shares_pkey PRIMARY KEY (id);


--
-- Name: shared_agent_links shared_agent_links_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.shared_agent_links
    ADD CONSTRAINT shared_agent_links_pkey PRIMARY KEY (id);


--
-- Name: shared_agent_links shared_agent_links_workflow_id_node_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.shared_agent_links
    ADD CONSTRAINT shared_agent_links_workflow_id_node_id_key UNIQUE (workflow_id, node_id);


--
-- Name: slack_installations slack_installations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.slack_installations
    ADD CONSTRAINT slack_installations_pkey PRIMARY KEY (id);


--
-- Name: slack_installations slack_installations_team_id_app_id_client_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.slack_installations
    ADD CONSTRAINT slack_installations_team_id_app_id_client_id_key UNIQUE (team_id, app_id, client_id);


--
-- Name: tool_call_events tool_call_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tool_call_events
    ADD CONSTRAINT tool_call_events_pkey PRIMARY KEY (id);


--
-- Name: resource_forks unique_fork; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.resource_forks
    ADD CONSTRAINT unique_fork UNIQUE (resource_type, source_id, forked_id);


--
-- Name: invite_redemptions unique_invite_redemption; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.invite_redemptions
    ADD CONSTRAINT unique_invite_redemption UNIQUE (invite_token, redeemer_id);


--
-- Name: organization_members unique_org_member; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.organization_members
    ADD CONSTRAINT unique_org_member UNIQUE (organization_id, user_id);


--
-- Name: organization_invites unique_pending_invite; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.organization_invites
    ADD CONSTRAINT unique_pending_invite UNIQUE (organization_id, email);


--
-- Name: credential_requests unique_pending_request; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.credential_requests
    ADD CONSTRAINT unique_pending_request UNIQUE (requester_id, target_email, credential_type);


--
-- Name: user_tables_metadata unique_user_virtual_table_name; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_tables_metadata
    ADD CONSTRAINT unique_user_virtual_table_name UNIQUE (owner_id, virtual_table_name);


--
-- Name: user_notification_preferences user_notification_preferences_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_notification_preferences
    ADD CONSTRAINT user_notification_preferences_pkey PRIMARY KEY (user_id);


--
-- Name: user_notifications user_notifications_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_notifications
    ADD CONSTRAINT user_notifications_pkey PRIMARY KEY (id);


--
-- Name: user_onboarding_completion user_onboarding_completion_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_onboarding_completion
    ADD CONSTRAINT user_onboarding_completion_pkey PRIMARY KEY (user_id);


--
-- Name: user_tables_metadata user_tables_metadata_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_tables_metadata
    ADD CONSTRAINT user_tables_metadata_pkey PRIMARY KEY (id);


--
-- Name: webhook_channels webhook_channels_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.webhook_channels
    ADD CONSTRAINT webhook_channels_pkey PRIMARY KEY (id);


--
-- Name: webhook_channels webhook_channels_workflow_node_unique; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.webhook_channels
    ADD CONSTRAINT webhook_channels_workflow_node_unique UNIQUE (workflow_id, node_id);


--
-- Name: webhook_subscriptions webhook_subscriptions_node_event_unique; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.webhook_subscriptions
    ADD CONSTRAINT webhook_subscriptions_node_event_unique UNIQUE (workflow_id, node_id, event_type);


--
-- Name: webhook_subscriptions webhook_subscriptions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.webhook_subscriptions
    ADD CONSTRAINT webhook_subscriptions_pkey PRIMARY KEY (id);


--
-- Name: webhooks webhooks_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.webhooks
    ADD CONSTRAINT webhooks_pkey PRIMARY KEY (id);


--
-- Name: webhooks webhooks_workflow_node_unique; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.webhooks
    ADD CONSTRAINT webhooks_workflow_node_unique UNIQUE (workflow_id, node_id);


--
-- Name: workflow_authorized_credentials workflow_authorized_credentials_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workflow_authorized_credentials
    ADD CONSTRAINT workflow_authorized_credentials_pkey PRIMARY KEY (workflow_id, credential_id);


--
-- Name: workflow_checkpoints workflow_checkpoints_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workflow_checkpoints
    ADD CONSTRAINT workflow_checkpoints_pkey PRIMARY KEY (id);


--
-- Name: workflow_executions workflow_executions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workflow_executions
    ADD CONSTRAINT workflow_executions_pkey PRIMARY KEY (id);


--
-- Name: workflow_folders workflow_folders_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workflow_folders
    ADD CONSTRAINT workflow_folders_pkey PRIMARY KEY (id);


--
-- Name: workflow_invite_links workflow_invite_links_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workflow_invite_links
    ADD CONSTRAINT workflow_invite_links_pkey PRIMARY KEY (id);


--
-- Name: workflow_invite_links workflow_invite_links_token_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workflow_invite_links
    ADD CONSTRAINT workflow_invite_links_token_key UNIQUE (token);


--
-- Name: workflow_node_output_schemas workflow_node_output_schemas_hash_unique; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workflow_node_output_schemas
    ADD CONSTRAINT workflow_node_output_schemas_hash_unique UNIQUE (schema_hash);


--
-- Name: workflow_node_output_schemas workflow_node_output_schemas_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workflow_node_output_schemas
    ADD CONSTRAINT workflow_node_output_schemas_pkey PRIMARY KEY (id);


--
-- Name: workflow_node_state workflow_node_state_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workflow_node_state
    ADD CONSTRAINT workflow_node_state_pkey PRIMARY KEY (id);


--
-- Name: workflow_node_state workflow_node_state_unique; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workflow_node_state
    ADD CONSTRAINT workflow_node_state_unique UNIQUE (workflow_id, node_id);


--
-- Name: workflow_resources workflow_resources_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workflow_resources
    ADD CONSTRAINT workflow_resources_pkey PRIMARY KEY (id);


--
-- Name: workflow_run_totals workflow_run_totals_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workflow_run_totals
    ADD CONSTRAINT workflow_run_totals_pkey PRIMARY KEY (workflow_id);


--
-- Name: workflow_saved_output workflow_saved_output_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workflow_saved_output
    ADD CONSTRAINT workflow_saved_output_pkey PRIMARY KEY (id);


--
-- Name: workflows workflows_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workflows
    ADD CONSTRAINT workflows_pkey PRIMARY KEY (id);


--
-- Name: idx_activity_logs_execution_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_activity_logs_execution_id ON public.activity_logs USING btree (execution_id);


--
-- Name: idx_activity_logs_org; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_activity_logs_org ON public.activity_logs USING btree (organization_id, created_at DESC) WHERE (organization_id IS NOT NULL);


--
-- Name: idx_activity_logs_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_activity_logs_user ON public.activity_logs USING btree (user_id, created_at DESC);


--
-- Name: idx_api_keys_hash; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX idx_api_keys_hash ON public.api_keys USING btree (key_hash);


--
-- Name: idx_api_keys_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_api_keys_user ON public.api_keys USING btree (user_id);


--
-- Name: idx_app_conversations; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_app_conversations ON public.conversations USING btree (app_id, last_activity DESC) WHERE ((app_id IS NOT NULL) AND (deleted_at IS NULL));


--
-- Name: idx_approval_requests_execution; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_approval_requests_execution ON public.approval_requests USING btree (execution_id, node_id);


--
-- Name: idx_approval_requests_org_pending; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_approval_requests_org_pending ON public.approval_requests USING btree (organization_id, created_at DESC) WHERE ((status = 'pending'::text) AND (organization_id IS NOT NULL));


--
-- Name: idx_approval_requests_user_pending; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_approval_requests_user_pending ON public.approval_requests USING btree (user_id, created_at DESC) WHERE (status = 'pending'::text);


--
-- Name: idx_cas_blobs_orphaned; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cas_blobs_orphaned ON public.cas_blobs USING btree (orphaned_at) WHERE (orphaned_at IS NOT NULL);


--
-- Name: idx_cas_manifests_node_recency; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cas_manifests_node_recency ON public.cas_manifests USING btree (workflow_id, node_id, created_at DESC);


--
-- Name: idx_cas_manifests_status_recency; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cas_manifests_status_recency ON public.cas_manifests USING btree (workflow_id, node_id, created_at DESC) INCLUDE (last_run_status, last_run_error) WHERE (last_run_status IS NOT NULL);


--
-- Name: idx_cas_manifests_workflow; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cas_manifests_workflow ON public.cas_manifests USING btree (workflow_id);


--
-- Name: idx_cas_refs_hash; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cas_refs_hash ON public.cas_refs USING btree (chunk_hash);


--
-- Name: idx_cas_refs_workflow; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cas_refs_workflow ON public.cas_refs USING btree (workflow_id);


--
-- Name: idx_conversation_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_conversation_id ON public.conversations USING btree (conversation_id) WHERE (deleted_at IS NULL);


--
-- Name: idx_conversations_paused; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_conversations_paused ON public.conversations USING btree (workflow_id, last_activity DESC) WHERE ((pending_ask IS NOT NULL) AND (deleted_at IS NULL));


--
-- Name: idx_conversations_workflow_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_conversations_workflow_id ON public.conversations USING btree (workflow_id) WHERE ((workflow_id IS NOT NULL) AND (deleted_at IS NULL));


--
-- Name: idx_credential_requests_requester; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_credential_requests_requester ON public.credential_requests USING btree (requester_id);


--
-- Name: idx_credential_requests_target_fulfilled; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_credential_requests_target_fulfilled ON public.credential_requests USING btree (target_email) WHERE (status = 'fulfilled'::text);


--
-- Name: idx_credentials_org; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_credentials_org ON public.credentials USING btree (organization_id) WHERE (organization_id IS NOT NULL);


--
-- Name: idx_credentials_owner_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_credentials_owner_type ON public.credentials USING btree (owner_id, credential_type);


--
-- Name: idx_credentials_personal; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_credentials_personal ON public.credentials USING btree (owner_id) WHERE (organization_id IS NULL);


--
-- Name: idx_credentials_revoked_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_credentials_revoked_at ON public.credentials USING btree (revoked_at DESC) WHERE (revoked_at IS NOT NULL);


--
-- Name: idx_deleted_conversations; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_deleted_conversations ON public.conversations USING btree (deleted_at) WHERE (deleted_at IS NOT NULL);


--
-- Name: idx_dr_resource; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_dr_resource ON public.dataset_rows USING btree (resource_id, row_index);


--
-- Name: idx_email_reservations_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_email_reservations_user_id ON public.email_reservations USING btree (user_id);


--
-- Name: idx_email_reservations_workflow_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_email_reservations_workflow_id ON public.email_reservations USING btree (workflow_id);


--
-- Name: idx_forks_by_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_forks_by_user ON public.resource_forks USING btree (forked_by);


--
-- Name: idx_forks_forked; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_forks_forked ON public.resource_forks USING btree (resource_type, forked_id);


--
-- Name: idx_forks_source; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_forks_source ON public.resource_forks USING btree (resource_type, source_id);


--
-- Name: idx_invite_redemptions_inviter; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_invite_redemptions_inviter ON public.invite_redemptions USING btree (inviter_id);


--
-- Name: idx_invite_redemptions_redeemer; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_invite_redemptions_redeemer ON public.invite_redemptions USING btree (redeemer_id);


--
-- Name: idx_invite_redemptions_token; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_invite_redemptions_token ON public.invite_redemptions USING btree (invite_token);


--
-- Name: idx_mcp_server_links_workflow; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_mcp_server_links_workflow ON public.mcp_server_links USING btree (workflow_id);


--
-- Name: idx_node_output_schemas_last_seen; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_node_output_schemas_last_seen ON public.workflow_node_output_schemas USING btree (last_seen_at DESC);


--
-- Name: idx_node_output_schemas_occurrence; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_node_output_schemas_occurrence ON public.workflow_node_output_schemas USING btree (node_type, node_operation, occurrence_count DESC);


--
-- Name: idx_node_output_schemas_type_operation; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_node_output_schemas_type_operation ON public.workflow_node_output_schemas USING btree (node_type, node_operation);


--
-- Name: idx_org_invites_email; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_org_invites_email ON public.organization_invites USING btree (email);


--
-- Name: idx_org_invites_org; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_org_invites_org ON public.organization_invites USING btree (organization_id);


--
-- Name: idx_org_invites_token; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_org_invites_token ON public.organization_invites USING btree (token);


--
-- Name: idx_org_members_org; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_org_members_org ON public.organization_members USING btree (organization_id);


--
-- Name: idx_org_members_org_role; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_org_members_org_role ON public.organization_members USING btree (organization_id, role);


--
-- Name: idx_org_members_primary; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_org_members_primary ON public.organization_members USING btree (user_id) WHERE (is_primary = true);


--
-- Name: idx_org_members_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_org_members_user ON public.organization_members USING btree (user_id);


--
-- Name: idx_organizations_personal_workspace; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_organizations_personal_workspace ON public.organizations USING btree (is_personal_workspace) WHERE (is_personal_workspace = true);


--
-- Name: idx_organizations_slug; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_organizations_slug ON public.organizations USING btree (slug);


--
-- Name: idx_organizations_sso_domain; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_organizations_sso_domain ON public.organizations USING btree (sso_domain) WHERE (sso_domain IS NOT NULL);


--
-- Name: idx_organizations_sso_provider_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_organizations_sso_provider_id ON public.organizations USING btree (sso_provider_id) WHERE (sso_provider_id IS NOT NULL);


--
-- Name: idx_resource_shares_target_folder; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_resource_shares_target_folder ON public.resource_shares USING btree (target_folder_id) WHERE (target_folder_id IS NOT NULL);


--
-- Name: idx_resource_shares_workflow_folder; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_resource_shares_workflow_folder ON public.resource_shares USING btree (resource_id, target_type) WHERE (resource_type = 'workflow_folder'::text);


--
-- Name: idx_saved_output_org_node; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_saved_output_org_node ON public.workflow_saved_output USING btree (organization_id, node_type) WHERE (organization_id IS NOT NULL);


--
-- Name: idx_saved_output_owner; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_saved_output_owner ON public.workflow_saved_output USING btree (owner_id);


--
-- Name: idx_saved_output_personal_node; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_saved_output_personal_node ON public.workflow_saved_output USING btree (owner_id, node_type) WHERE (organization_id IS NULL);


--
-- Name: idx_saved_output_public_node; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_saved_output_public_node ON public.workflow_saved_output USING btree (node_type) WHERE (is_public = true);


--
-- Name: idx_shared_agent_links_workflow; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_shared_agent_links_workflow ON public.shared_agent_links USING btree (workflow_id);


--
-- Name: idx_shares_org_resources; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_shares_org_resources ON public.resource_shares USING btree (target_org_id, resource_type, resource_id) WHERE (target_type = 'organization'::text);


--
-- Name: idx_shares_pending_email; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_shares_pending_email ON public.resource_shares USING btree (target_email, resource_type) WHERE (target_email IS NOT NULL);


--
-- Name: idx_shares_public_lookup; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_shares_public_lookup ON public.resource_shares USING btree (resource_id, resource_type) WHERE (target_type = 'public'::text);


--
-- Name: idx_shares_resource_lookup; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_shares_resource_lookup ON public.resource_shares USING btree (resource_type, resource_id);


--
-- Name: idx_shares_unique_email; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX idx_shares_unique_email ON public.resource_shares USING btree (resource_type, resource_id, target_email) WHERE ((target_type = 'user'::text) AND (target_email IS NOT NULL));


--
-- Name: idx_shares_unique_org; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX idx_shares_unique_org ON public.resource_shares USING btree (resource_type, resource_id, target_org_id) WHERE (target_type = 'organization'::text);


--
-- Name: idx_shares_unique_public; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX idx_shares_unique_public ON public.resource_shares USING btree (resource_type, resource_id) WHERE (target_type = 'public'::text);


--
-- Name: idx_shares_unique_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX idx_shares_unique_user_id ON public.resource_shares USING btree (resource_type, resource_id, target_user_id) WHERE ((target_type = 'user'::text) AND (target_user_id IS NOT NULL));


--
-- Name: idx_shares_user_resources; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_shares_user_resources ON public.resource_shares USING btree (target_user_id, resource_type, resource_id) WHERE ((target_type = 'user'::text) AND (target_user_id IS NOT NULL));


--
-- Name: idx_tool_call_events_conversation; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tool_call_events_conversation ON public.tool_call_events USING btree (conversation_id, created_at);


--
-- Name: idx_tool_call_events_execution; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tool_call_events_execution ON public.tool_call_events USING btree (execution_id, created_at);


--
-- Name: idx_tool_call_events_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tool_call_events_user ON public.tool_call_events USING btree (user_id, created_at DESC);


--
-- Name: idx_tool_call_events_workflow; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tool_call_events_workflow ON public.tool_call_events USING btree (workflow_id, created_at DESC);


--
-- Name: idx_user_conversations; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_user_conversations ON public.conversations USING btree (user_id, last_activity DESC) WHERE (deleted_at IS NULL);


--
-- Name: idx_user_notifications_user_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_user_notifications_user_created ON public.user_notifications USING btree (user_id, created_at DESC);


--
-- Name: idx_user_notifications_window; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_user_notifications_window ON public.user_notifications USING btree (user_id, dedupe_key, created_at DESC) WHERE (dedupe_key IS NOT NULL);


--
-- Name: idx_user_tables_metadata_credential; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_user_tables_metadata_credential ON public.user_tables_metadata USING btree (credential_id) WHERE (credential_id IS NOT NULL);


--
-- Name: idx_user_tables_org; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_user_tables_org ON public.user_tables_metadata USING btree (organization_id) WHERE (organization_id IS NOT NULL);


--
-- Name: idx_user_tables_org_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_user_tables_org_id ON public.user_tables_metadata USING btree (organization_id) WHERE (organization_id IS NOT NULL);


--
-- Name: idx_user_tables_org_owner; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_user_tables_org_owner ON public.user_tables_metadata USING btree (organization_id, owner_id) WHERE (organization_id IS NOT NULL);


--
-- Name: idx_user_tables_personal; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_user_tables_personal ON public.user_tables_metadata USING btree (owner_id) WHERE (organization_id IS NULL);


--
-- Name: idx_wac_workflow; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_wac_workflow ON public.workflow_authorized_credentials USING btree (workflow_id);


--
-- Name: idx_webhook_channels_renew_after; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_webhook_channels_renew_after ON public.webhook_channels USING btree (renew_after);


--
-- Name: idx_webhook_channels_workflow_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_webhook_channels_workflow_id ON public.webhook_channels USING btree (workflow_id);


--
-- Name: idx_webhook_subscriptions_lookup; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_webhook_subscriptions_lookup ON public.webhook_subscriptions USING btree (provider, tenant_id, event_type);


--
-- Name: idx_webhook_subscriptions_workflow_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_webhook_subscriptions_workflow_id ON public.webhook_subscriptions USING btree (workflow_id);


--
-- Name: idx_webhooks_org_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_webhooks_org_id ON public.webhooks USING btree (organization_id) WHERE (organization_id IS NOT NULL);


--
-- Name: idx_webhooks_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_webhooks_user_id ON public.webhooks USING btree (user_id);


--
-- Name: idx_webhooks_workflow_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_webhooks_workflow_id ON public.webhooks USING btree (workflow_id);


--
-- Name: idx_workflow_checkpoints_workflow_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_workflow_checkpoints_workflow_created ON public.workflow_checkpoints USING btree (workflow_id, created_at DESC);


--
-- Name: idx_workflow_executions_started_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_workflow_executions_started_at ON public.workflow_executions USING btree (started_at DESC);


--
-- Name: idx_workflow_executions_user_workflow; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_workflow_executions_user_workflow ON public.workflow_executions USING btree (user_id, workflow_id, started_at DESC);


--
-- Name: idx_workflow_executions_workflow_started; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_workflow_executions_workflow_started ON public.workflow_executions USING btree (workflow_id, started_at DESC) INCLUDE (status, trigger_source);


--
-- Name: idx_workflow_folders_owner_org; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_workflow_folders_owner_org ON public.workflow_folders USING btree (owner_id, organization_id);


--
-- Name: idx_workflow_folders_parent; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_workflow_folders_parent ON public.workflow_folders USING btree (parent_folder_id) WHERE (parent_folder_id IS NOT NULL);


--
-- Name: idx_workflow_folders_path; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_workflow_folders_path ON public.workflow_folders USING btree (path text_pattern_ops);


--
-- Name: idx_workflow_folders_unique_name; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX idx_workflow_folders_unique_name ON public.workflow_folders USING btree (owner_id, COALESCE((organization_id)::text, 'personal'::text), COALESCE((parent_folder_id)::text, 'root'::text), name);


--
-- Name: idx_workflow_invite_links_active; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX idx_workflow_invite_links_active ON public.workflow_invite_links USING btree (workflow_id) WHERE is_active;


--
-- Name: idx_workflow_invite_links_token_active; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_workflow_invite_links_token_active ON public.workflow_invite_links USING btree (token) WHERE is_active;


--
-- Name: idx_workflow_node_state_lookup; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_workflow_node_state_lookup ON public.workflow_node_state USING btree (workflow_id, node_id);


--
-- Name: idx_workflow_node_state_workflow_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_workflow_node_state_workflow_id ON public.workflow_node_state USING btree (workflow_id);


--
-- Name: idx_workflows_deleted_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_workflows_deleted_at ON public.workflows USING btree (deleted_at) WHERE (deleted_at IS NOT NULL);


--
-- Name: idx_workflows_folder_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_workflows_folder_id ON public.workflows USING btree (folder_id) WHERE (folder_id IS NOT NULL);


--
-- Name: idx_workflows_folder_owner_org; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_workflows_folder_owner_org ON public.workflows USING btree (folder_id, owner_id, organization_id);


--
-- Name: idx_workflows_org; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_workflows_org ON public.workflows USING btree (organization_id) WHERE (organization_id IS NOT NULL);


--
-- Name: idx_workflows_org_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_workflows_org_id ON public.workflows USING btree (organization_id) WHERE (organization_id IS NOT NULL);


--
-- Name: idx_workflows_org_owner; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_workflows_org_owner ON public.workflows USING btree (organization_id, owner_id) WHERE (organization_id IS NOT NULL);


--
-- Name: idx_workflows_personal; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_workflows_personal ON public.workflows USING btree (owner_id) WHERE (organization_id IS NULL);


--
-- Name: idx_workflows_updated_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_workflows_updated_at ON public.workflows USING btree (updated_at DESC);


--
-- Name: idx_workflows_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_workflows_user_id ON public.workflows USING btree (owner_id);


--
-- Name: idx_wr_owner; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_wr_owner ON public.workflow_resources USING btree (owner_id, updated_at DESC);


--
-- Name: idx_wr_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_wr_type ON public.workflow_resources USING btree (owner_id, resource_type);


--
-- Name: idx_wr_workflow_node; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_wr_workflow_node ON public.workflow_resources USING btree (workflow_id, node_id);


--
-- Name: local_cron_schedules_due_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX local_cron_schedules_due_idx ON public.local_cron_schedules USING btree (next_run) WHERE enabled;


--
-- Name: uniq_whatsapp_qr_connection_id; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uniq_whatsapp_qr_connection_id ON public.credentials USING btree (((metadata ->> 'connection_id'::text))) WHERE ((credential_type = 'whatsapp_qr'::text) AND ((metadata ->> 'connection_id'::text) IS NOT NULL));


--
-- Name: credentials credentials_token_version_bump; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER credentials_token_version_bump BEFORE UPDATE ON public.credentials FOR EACH ROW EXECUTE FUNCTION public.bump_token_version('credential');


--
-- Name: workflow_folders prevent_circular_folder_reference_trigger; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER prevent_circular_folder_reference_trigger BEFORE INSERT OR UPDATE OF parent_folder_id ON public.workflow_folders FOR EACH ROW EXECUTE FUNCTION public.prevent_circular_folder_reference();


--
-- Name: slack_installations slack_installations_token_version_bump; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER slack_installations_token_version_bump BEFORE UPDATE ON public.slack_installations FOR EACH ROW EXECUTE FUNCTION public.bump_token_version('installation');


--
-- Name: slack_installations slack_installations_touch_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER slack_installations_touch_updated_at BEFORE UPDATE ON public.slack_installations FOR EACH ROW EXECUTE FUNCTION public.slack_installations_touch_updated_at();


--
-- Name: user_onboarding_completion trigger_update_onboarding_completion_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trigger_update_onboarding_completion_updated_at BEFORE UPDATE ON public.user_onboarding_completion FOR EACH ROW EXECUTE FUNCTION public.update_onboarding_completion_updated_at();


--
-- Name: credentials update_credentials_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER update_credentials_updated_at BEFORE UPDATE ON public.credentials FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();


--
-- Name: email_reservations update_email_reservations_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER update_email_reservations_updated_at BEFORE UPDATE ON public.email_reservations FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();


--
-- Name: workflow_folders update_folder_path_and_depth_trigger; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER update_folder_path_and_depth_trigger BEFORE INSERT OR UPDATE OF parent_folder_id ON public.workflow_folders FOR EACH ROW EXECUTE FUNCTION public.update_folder_path_and_depth();


--
-- Name: organization_members update_organization_members_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER update_organization_members_updated_at BEFORE UPDATE ON public.organization_members FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();


--
-- Name: organizations update_organizations_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER update_organizations_updated_at BEFORE UPDATE ON public.organizations FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();


--
-- Name: user_notification_preferences update_user_notification_preferences_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER update_user_notification_preferences_updated_at BEFORE UPDATE ON public.user_notification_preferences FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();


--
-- Name: user_tables_metadata update_user_tables_metadata_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER update_user_tables_metadata_updated_at BEFORE UPDATE ON public.user_tables_metadata FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();


--
-- Name: webhook_channels update_webhook_channels_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER update_webhook_channels_updated_at BEFORE UPDATE ON public.webhook_channels FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();


--
-- Name: webhook_subscriptions update_webhook_subscriptions_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER update_webhook_subscriptions_updated_at BEFORE UPDATE ON public.webhook_subscriptions FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();


--
-- Name: webhooks update_webhooks_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER update_webhooks_updated_at BEFORE UPDATE ON public.webhooks FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();


--
-- Name: workflow_folders update_workflow_folder_updated_at_trigger; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER update_workflow_folder_updated_at_trigger BEFORE UPDATE ON public.workflow_folders FOR EACH ROW EXECUTE FUNCTION public.update_workflow_folder_updated_at();


--
-- Name: workflow_node_state update_workflow_node_state_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER update_workflow_node_state_updated_at BEFORE UPDATE ON public.workflow_node_state FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();


--
-- Name: workflow_saved_output update_workflow_saved_output_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER update_workflow_saved_output_updated_at BEFORE UPDATE ON public.workflow_saved_output FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();


--
-- Name: workflows update_workflows_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER update_workflows_updated_at BEFORE UPDATE ON public.workflows FOR EACH ROW EXECUTE FUNCTION public.workflows_touch_updated_at_content_only();


--
-- Name: workflows workflows_graph_version_bump; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER workflows_graph_version_bump BEFORE UPDATE ON public.workflows FOR EACH ROW EXECUTE FUNCTION public.bump_workflow_graph_version();


--
-- Name: activity_logs activity_logs_execution_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.activity_logs
    ADD CONSTRAINT activity_logs_execution_id_fkey FOREIGN KEY (execution_id) REFERENCES public.workflow_executions(id) ON DELETE CASCADE;


--
-- Name: activity_logs activity_logs_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.activity_logs
    ADD CONSTRAINT activity_logs_user_id_fkey FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE CASCADE;


--
-- Name: activity_logs activity_logs_workflow_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.activity_logs
    ADD CONSTRAINT activity_logs_workflow_id_fkey FOREIGN KEY (workflow_id) REFERENCES public.workflows(id) ON DELETE CASCADE;


--
-- Name: api_keys api_keys_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.api_keys
    ADD CONSTRAINT api_keys_user_id_fkey FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE CASCADE;


--
-- Name: api_keys api_keys_workflow_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.api_keys
    ADD CONSTRAINT api_keys_workflow_id_fkey FOREIGN KEY (workflow_id) REFERENCES public.workflows(id) ON DELETE CASCADE;


--
-- Name: approval_requests approval_requests_decided_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.approval_requests
    ADD CONSTRAINT approval_requests_decided_by_fkey FOREIGN KEY (decided_by) REFERENCES auth.users(id);


--
-- Name: approval_requests approval_requests_execution_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.approval_requests
    ADD CONSTRAINT approval_requests_execution_id_fkey FOREIGN KEY (execution_id) REFERENCES public.workflow_executions(id) ON DELETE CASCADE;


--
-- Name: approval_requests approval_requests_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.approval_requests
    ADD CONSTRAINT approval_requests_user_id_fkey FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE CASCADE;


--
-- Name: approval_requests approval_requests_workflow_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.approval_requests
    ADD CONSTRAINT approval_requests_workflow_id_fkey FOREIGN KEY (workflow_id) REFERENCES public.workflows(id) ON DELETE CASCADE;


--
-- Name: cas_manifests cas_manifests_workflow_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cas_manifests
    ADD CONSTRAINT cas_manifests_workflow_id_fkey FOREIGN KEY (workflow_id) REFERENCES public.workflows(id) ON DELETE CASCADE;


--
-- Name: cas_refs cas_refs_workflow_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cas_refs
    ADD CONSTRAINT cas_refs_workflow_id_fkey FOREIGN KEY (workflow_id) REFERENCES public.workflows(id) ON DELETE CASCADE;


--
-- Name: conversations conversations_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.conversations
    ADD CONSTRAINT conversations_user_id_fkey FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE CASCADE;


--
-- Name: credential_requests credential_requests_credential_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.credential_requests
    ADD CONSTRAINT credential_requests_credential_id_fkey FOREIGN KEY (credential_id) REFERENCES public.credentials(id) ON DELETE SET NULL;


--
-- Name: credential_requests credential_requests_requester_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.credential_requests
    ADD CONSTRAINT credential_requests_requester_id_fkey FOREIGN KEY (requester_id) REFERENCES auth.users(id) ON DELETE CASCADE;


--
-- Name: credentials credentials_organization_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.credentials
    ADD CONSTRAINT credentials_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES public.organizations(id) ON DELETE CASCADE;


--
-- Name: credentials credentials_owner_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.credentials
    ADD CONSTRAINT credentials_owner_id_fkey FOREIGN KEY (owner_id) REFERENCES auth.users(id) ON DELETE RESTRICT;


--
-- Name: dataset_rows dataset_rows_resource_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dataset_rows
    ADD CONSTRAINT dataset_rows_resource_id_fkey FOREIGN KEY (resource_id) REFERENCES public.workflow_resources(id) ON DELETE CASCADE;


--
-- Name: email_reservations email_reservations_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.email_reservations
    ADD CONSTRAINT email_reservations_user_id_fkey FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE CASCADE;


--
-- Name: email_reservations email_reservations_workflow_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.email_reservations
    ADD CONSTRAINT email_reservations_workflow_id_fkey FOREIGN KEY (workflow_id) REFERENCES public.workflows(id) ON DELETE CASCADE;


--
-- Name: instance_oauth_apps instance_oauth_apps_updated_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.instance_oauth_apps
    ADD CONSTRAINT instance_oauth_apps_updated_by_fkey FOREIGN KEY (updated_by) REFERENCES auth.users(id) ON DELETE SET NULL;


--
-- Name: invite_redemptions invite_redemptions_inviter_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.invite_redemptions
    ADD CONSTRAINT invite_redemptions_inviter_id_fkey FOREIGN KEY (inviter_id) REFERENCES auth.users(id) ON DELETE SET NULL;


--
-- Name: invite_redemptions invite_redemptions_redeemer_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.invite_redemptions
    ADD CONSTRAINT invite_redemptions_redeemer_id_fkey FOREIGN KEY (redeemer_id) REFERENCES auth.users(id) ON DELETE CASCADE;


--
-- Name: organization_invites organization_invites_invited_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.organization_invites
    ADD CONSTRAINT organization_invites_invited_by_fkey FOREIGN KEY (invited_by) REFERENCES auth.users(id);


--
-- Name: organization_invites organization_invites_organization_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.organization_invites
    ADD CONSTRAINT organization_invites_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES public.organizations(id) ON DELETE CASCADE;


--
-- Name: organization_members organization_members_invited_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.organization_members
    ADD CONSTRAINT organization_members_invited_by_fkey FOREIGN KEY (invited_by) REFERENCES auth.users(id);


--
-- Name: organization_members organization_members_organization_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.organization_members
    ADD CONSTRAINT organization_members_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES public.organizations(id) ON DELETE CASCADE;


--
-- Name: organization_members organization_members_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.organization_members
    ADD CONSTRAINT organization_members_user_id_fkey FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE CASCADE;


--
-- Name: resource_forks resource_forks_forked_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.resource_forks
    ADD CONSTRAINT resource_forks_forked_by_fkey FOREIGN KEY (forked_by) REFERENCES auth.users(id) ON DELETE CASCADE;


--
-- Name: resource_shares resource_shares_shared_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.resource_shares
    ADD CONSTRAINT resource_shares_shared_by_fkey FOREIGN KEY (shared_by) REFERENCES auth.users(id) ON DELETE CASCADE;


--
-- Name: resource_shares resource_shares_target_folder_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.resource_shares
    ADD CONSTRAINT resource_shares_target_folder_id_fkey FOREIGN KEY (target_folder_id) REFERENCES public.workflow_folders(id) ON DELETE SET NULL;


--
-- Name: resource_shares resource_shares_target_org_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.resource_shares
    ADD CONSTRAINT resource_shares_target_org_id_fkey FOREIGN KEY (target_org_id) REFERENCES public.organizations(id) ON DELETE CASCADE;


--
-- Name: resource_shares resource_shares_target_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.resource_shares
    ADD CONSTRAINT resource_shares_target_user_id_fkey FOREIGN KEY (target_user_id) REFERENCES auth.users(id) ON DELETE CASCADE;


--
-- Name: user_notification_preferences user_notification_preferences_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_notification_preferences
    ADD CONSTRAINT user_notification_preferences_user_id_fkey FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE CASCADE;


--
-- Name: user_notifications user_notifications_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_notifications
    ADD CONSTRAINT user_notifications_user_id_fkey FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE CASCADE;


--
-- Name: user_onboarding_completion user_onboarding_completion_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_onboarding_completion
    ADD CONSTRAINT user_onboarding_completion_user_id_fkey FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE CASCADE;


--
-- Name: user_tables_metadata user_tables_metadata_credential_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_tables_metadata
    ADD CONSTRAINT user_tables_metadata_credential_id_fkey FOREIGN KEY (credential_id) REFERENCES public.credentials(id) ON DELETE CASCADE;


--
-- Name: user_tables_metadata user_tables_metadata_organization_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_tables_metadata
    ADD CONSTRAINT user_tables_metadata_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES public.organizations(id) ON DELETE CASCADE;


--
-- Name: user_tables_metadata user_tables_metadata_owner_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_tables_metadata
    ADD CONSTRAINT user_tables_metadata_owner_id_fkey FOREIGN KEY (owner_id) REFERENCES auth.users(id) ON DELETE RESTRICT;


--
-- Name: webhook_channels webhook_channels_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.webhook_channels
    ADD CONSTRAINT webhook_channels_user_id_fkey FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE CASCADE;


--
-- Name: webhook_channels webhook_channels_webhook_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.webhook_channels
    ADD CONSTRAINT webhook_channels_webhook_id_fkey FOREIGN KEY (webhook_id) REFERENCES public.webhooks(id) ON DELETE CASCADE;


--
-- Name: webhook_channels webhook_channels_workflow_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.webhook_channels
    ADD CONSTRAINT webhook_channels_workflow_id_fkey FOREIGN KEY (workflow_id) REFERENCES public.workflows(id) ON DELETE CASCADE;


--
-- Name: webhook_subscriptions webhook_subscriptions_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.webhook_subscriptions
    ADD CONSTRAINT webhook_subscriptions_user_id_fkey FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE CASCADE;


--
-- Name: webhook_subscriptions webhook_subscriptions_workflow_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.webhook_subscriptions
    ADD CONSTRAINT webhook_subscriptions_workflow_id_fkey FOREIGN KEY (workflow_id) REFERENCES public.workflows(id) ON DELETE CASCADE;


--
-- Name: webhooks webhooks_organization_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.webhooks
    ADD CONSTRAINT webhooks_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES public.organizations(id) ON DELETE SET NULL;


--
-- Name: webhooks webhooks_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.webhooks
    ADD CONSTRAINT webhooks_user_id_fkey FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE CASCADE;


--
-- Name: webhooks webhooks_workflow_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.webhooks
    ADD CONSTRAINT webhooks_workflow_id_fkey FOREIGN KEY (workflow_id) REFERENCES public.workflows(id) ON DELETE CASCADE;


--
-- Name: workflow_authorized_credentials workflow_authorized_credentials_authorized_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workflow_authorized_credentials
    ADD CONSTRAINT workflow_authorized_credentials_authorized_by_fkey FOREIGN KEY (authorized_by) REFERENCES auth.users(id) ON DELETE SET NULL;


--
-- Name: workflow_authorized_credentials workflow_authorized_credentials_credential_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workflow_authorized_credentials
    ADD CONSTRAINT workflow_authorized_credentials_credential_id_fkey FOREIGN KEY (credential_id) REFERENCES public.credentials(id) ON DELETE CASCADE;


--
-- Name: workflow_authorized_credentials workflow_authorized_credentials_workflow_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workflow_authorized_credentials
    ADD CONSTRAINT workflow_authorized_credentials_workflow_id_fkey FOREIGN KEY (workflow_id) REFERENCES public.workflows(id) ON DELETE CASCADE;


--
-- Name: workflow_checkpoints workflow_checkpoints_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workflow_checkpoints
    ADD CONSTRAINT workflow_checkpoints_user_id_fkey FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE CASCADE;


--
-- Name: workflow_checkpoints workflow_checkpoints_workflow_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workflow_checkpoints
    ADD CONSTRAINT workflow_checkpoints_workflow_id_fkey FOREIGN KEY (workflow_id) REFERENCES public.workflows(id) ON DELETE CASCADE;


--
-- Name: workflow_executions workflow_executions_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workflow_executions
    ADD CONSTRAINT workflow_executions_user_id_fkey FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE CASCADE;


--
-- Name: workflow_executions workflow_executions_workflow_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workflow_executions
    ADD CONSTRAINT workflow_executions_workflow_id_fkey FOREIGN KEY (workflow_id) REFERENCES public.workflows(id) ON DELETE CASCADE;


--
-- Name: workflow_folders workflow_folders_organization_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workflow_folders
    ADD CONSTRAINT workflow_folders_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES public.organizations(id) ON DELETE CASCADE;


--
-- Name: workflow_folders workflow_folders_owner_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workflow_folders
    ADD CONSTRAINT workflow_folders_owner_id_fkey FOREIGN KEY (owner_id) REFERENCES auth.users(id) ON DELETE RESTRICT;


--
-- Name: workflow_folders workflow_folders_parent_folder_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workflow_folders
    ADD CONSTRAINT workflow_folders_parent_folder_id_fkey FOREIGN KEY (parent_folder_id) REFERENCES public.workflow_folders(id) ON DELETE CASCADE;


--
-- Name: workflow_invite_links workflow_invite_links_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workflow_invite_links
    ADD CONSTRAINT workflow_invite_links_created_by_fkey FOREIGN KEY (created_by) REFERENCES auth.users(id) ON DELETE CASCADE;


--
-- Name: workflow_invite_links workflow_invite_links_workflow_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workflow_invite_links
    ADD CONSTRAINT workflow_invite_links_workflow_id_fkey FOREIGN KEY (workflow_id) REFERENCES public.workflows(id) ON DELETE CASCADE;


--
-- Name: workflow_node_state workflow_node_state_workflow_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workflow_node_state
    ADD CONSTRAINT workflow_node_state_workflow_id_fkey FOREIGN KEY (workflow_id) REFERENCES public.workflows(id) ON DELETE CASCADE;


--
-- Name: workflow_resources workflow_resources_organization_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workflow_resources
    ADD CONSTRAINT workflow_resources_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES public.organizations(id) ON DELETE CASCADE;


--
-- Name: workflow_resources workflow_resources_owner_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workflow_resources
    ADD CONSTRAINT workflow_resources_owner_id_fkey FOREIGN KEY (owner_id) REFERENCES auth.users(id) ON DELETE RESTRICT;


--
-- Name: workflow_resources workflow_resources_workflow_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workflow_resources
    ADD CONSTRAINT workflow_resources_workflow_id_fkey FOREIGN KEY (workflow_id) REFERENCES public.workflows(id) ON DELETE CASCADE;


--
-- Name: workflow_saved_output workflow_saved_output_organization_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workflow_saved_output
    ADD CONSTRAINT workflow_saved_output_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES public.organizations(id) ON DELETE CASCADE;


--
-- Name: workflow_saved_output workflow_saved_output_owner_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workflow_saved_output
    ADD CONSTRAINT workflow_saved_output_owner_id_fkey FOREIGN KEY (owner_id) REFERENCES auth.users(id) ON DELETE RESTRICT;


--
-- Name: workflows workflows_folder_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workflows
    ADD CONSTRAINT workflows_folder_id_fkey FOREIGN KEY (folder_id) REFERENCES public.workflow_folders(id) ON DELETE SET NULL;


--
-- Name: workflows workflows_organization_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workflows
    ADD CONSTRAINT workflows_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES public.organizations(id) ON DELETE CASCADE;


--
-- Name: workflows workflows_owner_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workflows
    ADD CONSTRAINT workflows_owner_id_fkey FOREIGN KEY (owner_id) REFERENCES auth.users(id) ON DELETE RESTRICT;


--
-- Name: organization_members Admins can add members; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY "Admins can add members" ON public.organization_members FOR INSERT WITH CHECK (((role = ANY (ARRAY['admin'::text, 'member'::text])) AND (organization_id IN ( SELECT public.user_admin_organization_ids() AS user_admin_organization_ids))));


--
-- Name: organization_invites Admins can manage invites; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY "Admins can manage invites" ON public.organization_invites USING ((organization_id IN ( SELECT organization_members.organization_id
   FROM public.organization_members
  WHERE ((organization_members.user_id = auth.uid()) AND (organization_members.role = ANY (ARRAY['owner'::text, 'admin'::text]))))));


--
-- Name: organization_members Admins can remove members; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY "Admins can remove members" ON public.organization_members FOR DELETE USING (((role <> 'owner'::text) AND (organization_id IN ( SELECT public.user_admin_organization_ids() AS user_admin_organization_ids))));


--
-- Name: organization_members Admins can update members; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY "Admins can update members" ON public.organization_members FOR UPDATE USING ((organization_id IN ( SELECT public.user_admin_organization_ids() AS user_admin_organization_ids))) WITH CHECK ((role = ANY (ARRAY['admin'::text, 'member'::text])));


--
-- Name: organizations Admins can update organization; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY "Admins can update organization" ON public.organizations FOR UPDATE USING ((id IN ( SELECT organization_members.organization_id
   FROM public.organization_members
  WHERE ((organization_members.user_id = auth.uid()) AND (organization_members.role = ANY (ARRAY['owner'::text, 'admin'::text]))))));


-- CAS, execution logs and approval state are backend-only. They deliberately
-- have no anon/authenticated policy: exposing them through PostgREST bypasses
-- the workflow/org authorization enforced by the backend repositories.


--
-- Name: cas_blobs Allow all for service_role; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY "Allow all for service_role" ON public.cas_blobs TO service_role USING (true) WITH CHECK (true);


--
-- Name: cas_manifests Allow all for service_role; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY "Allow all for service_role" ON public.cas_manifests TO service_role USING (true) WITH CHECK (true);


--
-- Name: cas_refs Allow all for service_role; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY "Allow all for service_role" ON public.cas_refs TO service_role USING (true) WITH CHECK (true);


--
-- Name: cas_storage_stats Allow all for service_role; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY "Allow all for service_role" ON public.cas_storage_stats TO service_role USING (true) WITH CHECK (true);


--
-- Name: workflow_run_totals Allow all for service_role; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY "Allow all for service_role" ON public.workflow_run_totals TO service_role USING (true) WITH CHECK (true);


--
-- Name: resource_forks Anyone can view fork relationships; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY "Anyone can view fork relationships" ON public.resource_forks FOR SELECT USING (true);


--
-- Name: organizations Authenticated users can create organizations; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY "Authenticated users can create organizations" ON public.organizations FOR INSERT TO authenticated WITH CHECK (true);


--
-- Name: organization_members Creator can add self as owner; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY "Creator can add self as owner" ON public.organization_members FOR INSERT TO authenticated WITH CHECK (((user_id = auth.uid()) AND (role = 'owner'::text) AND (NOT public.organization_has_members(organization_id))));


--
-- Name: organization_members Members can leave org; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY "Members can leave org" ON public.organization_members FOR DELETE USING (((user_id = auth.uid()) AND (role <> 'owner'::text)));


--
-- Name: organization_invites Members can view org invites; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY "Members can view org invites" ON public.organization_invites FOR SELECT USING ((organization_id IN ( SELECT organization_members.organization_id
   FROM public.organization_members
  WHERE (organization_members.user_id = auth.uid()))));


--
-- Name: organization_members Members can view org members; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY "Members can view org members" ON public.organization_members FOR SELECT USING ((organization_id IN ( SELECT public.user_organization_ids() AS user_organization_ids)));


--
-- Name: organizations Members can view own organization; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY "Members can view own organization" ON public.organizations FOR SELECT USING ((id IN ( SELECT organization_members.organization_id
   FROM public.organization_members
  WHERE (organization_members.user_id = auth.uid()))));


--
-- Name: workflow_invite_links Owners can create invite links; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY "Owners can create invite links" ON public.workflow_invite_links FOR INSERT WITH CHECK (((created_by = auth.uid()) AND (EXISTS ( SELECT 1
   FROM public.workflows w
  WHERE ((w.id = workflow_invite_links.workflow_id) AND (w.owner_id = auth.uid()) AND (w.deleted_at IS NULL))))));


--
-- Name: organizations Owners can delete organization; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY "Owners can delete organization" ON public.organizations FOR DELETE USING ((id IN ( SELECT organization_members.organization_id
   FROM public.organization_members
  WHERE ((organization_members.user_id = auth.uid()) AND (organization_members.role = 'owner'::text)))));


--
-- Name: workflow_invite_links Owners can delete their invite links; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY "Owners can delete their invite links" ON public.workflow_invite_links FOR DELETE USING ((created_by = auth.uid()));


--
-- Name: workflow_invite_links Owners can update their invite links; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY "Owners can update their invite links" ON public.workflow_invite_links FOR UPDATE USING ((created_by = auth.uid())) WITH CHECK (((created_by = auth.uid()) AND (EXISTS ( SELECT 1
   FROM public.workflows w
  WHERE ((w.id = workflow_invite_links.workflow_id) AND (w.owner_id = auth.uid()) AND (w.deleted_at IS NULL))))));


--
-- Name: workflow_invite_links Owners can view their invite links; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY "Owners can view their invite links" ON public.workflow_invite_links FOR SELECT USING ((created_by = auth.uid()));


--
-- Name: dataset_rows Service role full access dr; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY "Service role full access dr" ON public.dataset_rows TO service_role USING (true);


--
-- Name: resource_forks Service role full access to forks; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY "Service role full access to forks" ON public.resource_forks TO service_role USING (true);


--
-- Name: workflow_invite_links Service role full access to invite links; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY "Service role full access to invite links" ON public.workflow_invite_links TO service_role USING (true);


--
-- Name: invite_redemptions Service role full access to invite redemptions; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY "Service role full access to invite redemptions" ON public.invite_redemptions TO service_role USING (true);


--
-- Name: organization_invites Service role full access to invites; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY "Service role full access to invites" ON public.organization_invites TO service_role USING (true);


--
-- Name: organization_members Service role full access to members; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY "Service role full access to members" ON public.organization_members TO service_role USING (true);


--
-- Name: user_onboarding_completion Service role full access to onboarding completion; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY "Service role full access to onboarding completion" ON public.user_onboarding_completion TO service_role USING (true);


--
-- Name: organizations Service role full access to organizations; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY "Service role full access to organizations" ON public.organizations TO service_role USING (true);


--
-- Name: resource_shares Service role full access to shares; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY "Service role full access to shares" ON public.resource_shares TO service_role USING (true);


--
-- Name: workflow_resources Service role full access wr; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY "Service role full access wr" ON public.workflow_resources TO service_role USING (true);


--
-- Name: dataset_rows Users can access own dataset rows; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY "Users can access own dataset rows" ON public.dataset_rows USING ((resource_id IN ( SELECT workflow_resources.id
   FROM public.workflow_resources
  WHERE (workflow_resources.owner_id = auth.uid()))));


--
-- Name: workflow_resources Users can access own resources; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY "Users can access own resources" ON public.workflow_resources USING ((owner_id = auth.uid()));


--
-- Name: resource_forks Users can create fork records; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY "Users can create fork records" ON public.resource_forks FOR INSERT WITH CHECK ((forked_by = auth.uid()));


--
-- Name: resource_forks Users can delete own fork records; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY "Users can delete own fork records" ON public.resource_forks FOR DELETE USING ((forked_by = auth.uid()));


--
-- Name: workflow_executions Users can delete their own execution logs; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY "Users can delete their own execution logs" ON public.workflow_executions FOR DELETE USING ((auth.uid() = user_id));


--
-- Name: conversations Users can insert own conversations; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY "Users can insert own conversations" ON public.conversations FOR INSERT WITH CHECK ((auth.uid() = user_id));


--
-- Name: user_onboarding_completion Users can insert own onboarding completion; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY "Users can insert own onboarding completion" ON public.user_onboarding_completion FOR INSERT TO authenticated WITH CHECK ((user_id = auth.uid()));


--
-- Name: workflow_executions Users can insert their own execution logs; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY "Users can insert their own execution logs" ON public.workflow_executions FOR INSERT WITH CHECK ((auth.uid() = user_id));


--
-- Name: conversations Users can soft delete own conversations; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY "Users can soft delete own conversations" ON public.conversations FOR UPDATE USING ((auth.uid() = user_id)) WITH CHECK ((auth.uid() = user_id));


--
-- Name: conversations Users can update own conversations; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY "Users can update own conversations" ON public.conversations FOR UPDATE USING (((auth.uid() = user_id) AND (deleted_at IS NULL)));


--
-- Name: user_onboarding_completion Users can update own onboarding completion; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY "Users can update own onboarding completion" ON public.user_onboarding_completion FOR UPDATE USING ((user_id = auth.uid()));


--
-- Name: workflow_executions Users can update their own execution logs; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY "Users can update their own execution logs" ON public.workflow_executions FOR UPDATE USING ((auth.uid() = user_id));


--
-- Name: conversations Users can view own conversations; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY "Users can view own conversations" ON public.conversations FOR SELECT USING (((auth.uid() = user_id) AND (deleted_at IS NULL)));


--
-- Name: user_onboarding_completion Users can view own onboarding completion; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY "Users can view own onboarding completion" ON public.user_onboarding_completion FOR SELECT USING ((user_id = auth.uid()));


--
-- Name: invite_redemptions Users can view redemptions they are part of; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY "Users can view redemptions they are part of" ON public.invite_redemptions FOR SELECT USING (((inviter_id = auth.uid()) OR (redeemer_id = auth.uid())));


--
-- Name: resource_shares Users can view shares for accessible resources; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY "Users can view shares for accessible resources" ON public.resource_shares FOR SELECT USING (((shared_by = auth.uid()) OR (target_user_id = auth.uid()) OR (target_org_id IN ( SELECT organization_members.organization_id
   FROM public.organization_members
  WHERE (organization_members.user_id = auth.uid())))));


--
-- Name: workflow_executions Users can view their own execution logs; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY "Users can view their own execution logs" ON public.workflow_executions FOR SELECT USING ((auth.uid() = user_id));


--
-- Name: tool_call_events Users can view their own tool call events; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY "Users can view their own tool call events" ON public.tool_call_events FOR SELECT USING ((auth.uid() = user_id));


--
-- Name: activity_logs; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.activity_logs ENABLE ROW LEVEL SECURITY;

--
-- Name: api_keys; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.api_keys ENABLE ROW LEVEL SECURITY;

--
-- Name: api_keys api_keys_user_policy; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY api_keys_user_policy ON public.api_keys USING ((user_id = auth.uid()));


--
-- Name: approval_requests; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.approval_requests ENABLE ROW LEVEL SECURITY;

--
-- Name: cas_blobs; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.cas_blobs ENABLE ROW LEVEL SECURITY;

--
-- Name: cas_manifests; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.cas_manifests ENABLE ROW LEVEL SECURITY;

--
-- Name: cas_refs; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.cas_refs ENABLE ROW LEVEL SECURITY;

--
-- Name: cas_storage_stats; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.cas_storage_stats ENABLE ROW LEVEL SECURITY;

--
-- Name: conversations; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.conversations ENABLE ROW LEVEL SECURITY;

--
-- Name: credential_requests; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.credential_requests ENABLE ROW LEVEL SECURITY;

--
-- Name: credential_requests credential_requests_insert; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY credential_requests_insert ON public.credential_requests FOR INSERT WITH CHECK ((auth.uid() = requester_id));


--
-- Name: credential_requests credential_requests_select; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY credential_requests_select ON public.credential_requests FOR SELECT USING ((auth.uid() = requester_id));


--
-- Name: credential_requests credential_requests_service; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY credential_requests_service ON public.credential_requests TO service_role USING (true) WITH CHECK (true);


--
-- Name: credential_requests credential_requests_update; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY credential_requests_update ON public.credential_requests FOR UPDATE USING ((auth.uid() = requester_id));


--
-- Name: credentials; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.credentials ENABLE ROW LEVEL SECURITY;

--
-- Name: dataset_rows; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.dataset_rows ENABLE ROW LEVEL SECURITY;

--
-- Name: email_reservations; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.email_reservations ENABLE ROW LEVEL SECURITY;

--
-- Name: instance_oauth_apps; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.instance_oauth_apps ENABLE ROW LEVEL SECURITY;

--
-- Name: invite_redemptions; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.invite_redemptions ENABLE ROW LEVEL SECURITY;

--
-- Name: mcp_server_links; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.mcp_server_links ENABLE ROW LEVEL SECURITY;

--
-- Name: organization_invites; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.organization_invites ENABLE ROW LEVEL SECURITY;

--
-- Name: organization_members; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.organization_members ENABLE ROW LEVEL SECURITY;

--
-- Name: organizations; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.organizations ENABLE ROW LEVEL SECURITY;

--
-- Name: resource_forks; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.resource_forks ENABLE ROW LEVEL SECURITY;

--
-- Name: resource_shares; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.resource_shares ENABLE ROW LEVEL SECURITY;

--
-- Name: shared_agent_links; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.shared_agent_links ENABLE ROW LEVEL SECURITY;

--
-- Name: slack_installations; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.slack_installations ENABLE ROW LEVEL SECURITY;

--
-- Name: tool_call_events; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.tool_call_events ENABLE ROW LEVEL SECURITY;

--
-- Name: user_notification_preferences; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.user_notification_preferences ENABLE ROW LEVEL SECURITY;

--
-- Name: user_notifications; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.user_notifications ENABLE ROW LEVEL SECURITY;

--
-- Name: user_onboarding_completion; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.user_onboarding_completion ENABLE ROW LEVEL SECURITY;

--
-- Name: user_tables_metadata; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.user_tables_metadata ENABLE ROW LEVEL SECURITY;

--
-- Name: webhook_channels; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.webhook_channels ENABLE ROW LEVEL SECURITY;

--
-- Name: webhook_subscriptions; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.webhook_subscriptions ENABLE ROW LEVEL SECURITY;

--
-- Name: webhooks; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.webhooks ENABLE ROW LEVEL SECURITY;

--
-- Name: workflow_authorized_credentials; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.workflow_authorized_credentials ENABLE ROW LEVEL SECURITY;

--
-- Name: workflow_checkpoints; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.workflow_checkpoints ENABLE ROW LEVEL SECURITY;

--
-- Name: workflow_executions; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.workflow_executions ENABLE ROW LEVEL SECURITY;

--
-- Name: workflow_folders; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.workflow_folders ENABLE ROW LEVEL SECURITY;

--
-- Name: workflow_folders workflow_folders_delete_policy; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY workflow_folders_delete_policy ON public.workflow_folders FOR DELETE USING ((owner_id = auth.uid()));


--
-- Name: workflow_folders workflow_folders_insert_policy; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY workflow_folders_insert_policy ON public.workflow_folders FOR INSERT WITH CHECK ((((owner_id = auth.uid()) AND (organization_id IS NULL)) OR ((owner_id = auth.uid()) AND (organization_id IS NOT NULL) AND (EXISTS ( SELECT 1
   FROM public.organization_members om
  WHERE ((om.organization_id = workflow_folders.organization_id) AND (om.user_id = auth.uid())))))));


--
-- Name: workflow_folders workflow_folders_select_policy; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY workflow_folders_select_policy ON public.workflow_folders FOR SELECT USING (((owner_id = auth.uid()) OR ((organization_id IS NOT NULL) AND (EXISTS ( SELECT 1
   FROM public.organization_members om
  WHERE ((om.organization_id = workflow_folders.organization_id) AND (om.user_id = auth.uid()))))) OR (EXISTS ( SELECT 1
   FROM public.resource_shares rs
  WHERE ((rs.resource_type = 'workflow_folder'::text) AND (rs.resource_id = workflow_folders.id) AND (rs.target_type = 'user'::text) AND (rs.target_user_id = auth.uid()))))));


--
-- Name: workflow_folders workflow_folders_update_policy; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY workflow_folders_update_policy ON public.workflow_folders FOR UPDATE USING ((owner_id = auth.uid())) WITH CHECK ((owner_id = auth.uid()));


--
-- Name: workflow_invite_links; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.workflow_invite_links ENABLE ROW LEVEL SECURITY;

--
-- Name: workflow_node_output_schemas; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.workflow_node_output_schemas ENABLE ROW LEVEL SECURITY;

--
-- Name: workflow_node_state; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.workflow_node_state ENABLE ROW LEVEL SECURITY;

--
-- Name: workflow_resources; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.workflow_resources ENABLE ROW LEVEL SECURITY;

--
-- Name: workflow_run_totals; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.workflow_run_totals ENABLE ROW LEVEL SECURITY;

--
-- Name: workflow_saved_output; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.workflow_saved_output ENABLE ROW LEVEL SECURITY;

--
-- Name: workflows; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.workflows ENABLE ROW LEVEL SECURITY;

-- Supabase authentication lifecycle integration. These triggers live on the
-- auth schema, so a public-schema dump does not emit them automatically.
DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
AFTER INSERT ON auth.users
FOR EACH ROW EXECUTE FUNCTION public.handle_new_user_registration();

DROP TRIGGER IF EXISTS after_user_signup_convert_shares ON auth.users;
CREATE TRIGGER after_user_signup_convert_shares
AFTER INSERT ON auth.users
FOR EACH ROW EXECUTE FUNCTION public.convert_pending_shares();

DROP TRIGGER IF EXISTS on_auth_user_created_init_onboarding_completion ON auth.users;
CREATE TRIGGER on_auth_user_created_init_onboarding_completion
AFTER INSERT ON auth.users
FOR EACH ROW EXECUTE FUNCTION public.init_user_onboarding_completion();

DROP TRIGGER IF EXISTS before_user_delete ON auth.users;
CREATE TRIGGER before_user_delete
BEFORE DELETE ON auth.users
FOR EACH ROW EXECUTE FUNCTION public.handle_user_deletion();

DROP TRIGGER IF EXISTS on_sso_identity_created ON auth.identities;
CREATE TRIGGER on_sso_identity_created
AFTER INSERT ON auth.identities
FOR EACH ROW EXECUTE FUNCTION public.handle_sso_user_login();

-- PostgREST roles receive table privileges, while row-level policies remain the
-- authorization boundary. Tables without a policy stay inaccessible.
GRANT USAGE ON SCHEMA public TO authenticated, service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO authenticated;
GRANT ALL ON ALL TABLES IN SCHEMA public TO service_role;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO authenticated, service_role;

REVOKE ALL ON FUNCTION public.handle_new_user_registration() FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.handle_user_deletion() FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.handle_sso_user_login() FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.convert_pending_shares() FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.init_user_onboarding_completion() FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.custom_access_token_hook(jsonb) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.custom_access_token_hook(jsonb) TO supabase_auth_admin;
GRANT EXECUTE ON FUNCTION public.handle_new_user_registration() TO service_role;
GRANT EXECUTE ON FUNCTION public.handle_user_deletion() TO service_role;
GRANT EXECUTE ON FUNCTION public.handle_sso_user_login() TO service_role;
GRANT EXECUTE ON FUNCTION public.convert_pending_shares() TO service_role;
GRANT EXECUTE ON FUNCTION public.init_user_onboarding_completion() TO service_role;

--
-- PostgreSQL database dump complete
--

--
-- Name: backend-only tables; Type: ACL/RLS; Schema: public; Owner: -
--
-- The blanket grant above hands the API roles table privileges and leans on
-- row-level security to decide who sees what. That is sound for every table
-- with RLS enabled — no policy means no rows — and nothing at all for a table
-- without it, where the grant is the whole story.
--
-- local_cron_schedules was such a table. Over PostgREST any signed-in user
-- could read every schedule's webhook_url — the capability that fires that
-- workflow — and insert a row that made the scheduler POST a payload of their
-- choosing to a host of their choosing, on a timer, from the instance.
--
-- Revoking as well as enabling RLS means a policy added by mistake, or a table
-- re-created without RLS, still fails closed. The service role and the
-- backend's own connection are unaffected.
--
ALTER TABLE public.local_cron_schedules ENABLE ROW LEVEL SECURITY;

-- Tables the API roles have no business touching. Each is already RLS-enabled with
-- no policies (or is above); the revoke is the second lock. Service role and the
-- backend's own connection are unaffected — they bypass RLS and keep their grants.
REVOKE ALL ON TABLE
    public.activity_logs,
    public.approval_requests,
    public.cas_blobs,
    public.cas_manifests,
    public.cas_refs,
    public.cas_storage_stats,
    public.local_cron_schedules,
    public.credentials,
    public.email_reservations,
    public.instance_oauth_apps,
    public.mcp_server_links,
    public.shared_agent_links,
    public.slack_installations,
    public.user_notification_preferences,
    public.user_notifications,
    public.user_tables_metadata,
    public.webhook_channels,
    public.webhook_subscriptions,
    public.webhooks,
    public.workflow_authorized_credentials,
    public.workflow_checkpoints,
    public.workflow_node_output_schemas,
    public.workflow_node_state,
    public.workflow_run_totals,
    public.workflow_saved_output,
    public.workflows
FROM anon, authenticated;

-- resource_shares keeps SELECT: sharing is visible to the people shared with.
-- Writes go through the backend, which checks ownership. A forged self-grant row
-- here would hand its author someone else's workflow, and with it the credentials
-- that workflow runs as.
REVOKE INSERT, UPDATE, DELETE ON TABLE public.resource_shares FROM anon, authenticated;
