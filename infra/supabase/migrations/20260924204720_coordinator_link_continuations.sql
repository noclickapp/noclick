-- A link is an awaited result in the existing inbox, not a second job queue.
-- Resource transitions queue its continuation in the SAME transaction, even
-- when a new provider route forgets the optional immediate scheduler dispatch.
ALTER TABLE public.coordinator_wakeups
    ADD COLUMN await_key text,
    ADD COLUMN await_expires_at timestamptz;
ALTER TABLE public.coordinator_wakeups DROP CONSTRAINT coordinator_wakeups_status_check;
ALTER TABLE public.coordinator_wakeups ADD CONSTRAINT coordinator_wakeups_status_check
    CHECK (status IN ('waiting','queued','running','ready','delivering','done','skipped'));
ALTER TABLE public.coordinator_wakeups DROP CONSTRAINT coordinator_wakeups_source_check;
ALTER TABLE public.coordinator_wakeups ADD CONSTRAINT coordinator_wakeups_source_check
    CHECK (source IN ('job','alarm','signal','credential_approval','link'));
ALTER TABLE public.coordinator_wakeups ADD CONSTRAINT coordinator_link_wait_target
    CHECK (status <> 'waiting' OR (source='link' AND await_key IS NOT NULL AND await_expires_at IS NOT NULL));
CREATE UNIQUE INDEX coordinator_link_waiting ON public.coordinator_wakeups(user_id, await_key)
    WHERE status='waiting';
CREATE INDEX coordinator_link_target ON public.coordinator_wakeups(await_key)
    WHERE source='link' AND status IN ('waiting','queued');
CREATE INDEX coordinator_link_expiry ON public.coordinator_wakeups(await_expires_at)
    WHERE status='waiting';

CREATE FUNCTION public.complete_coordinator_link(target text, outcome jsonb) RETURNS void
LANGUAGE sql SET search_path = '' AS $$
    UPDATE public.coordinator_wakeups SET status='queued',
        payload=payload || outcome, not_before=now(), dispatch_after=now()
    WHERE source='link' AND status='waiting' AND await_key=target;
$$;
REVOKE ALL ON FUNCTION public.complete_coordinator_link(text,jsonb) FROM PUBLIC, anon, authenticated;

CREATE FUNCTION public.credential_request_complete_link() RETURNS trigger
LANGUAGE plpgsql SET search_path = '' AS $$
BEGIN
    IF NEW.token IS DISTINCT FROM OLD.token THEN
        -- A refreshed link must never complete a previous request's continuation.
        UPDATE public.coordinator_wakeups SET status='skipped'
        WHERE status='waiting' AND await_key='credential_request:' || NEW.id::text;
    ELSIF NEW.status IS DISTINCT FROM OLD.status AND NEW.status IN ('fulfilled','cancelled','expired') THEN
        PERFORM public.complete_coordinator_link('credential_request:' || NEW.id::text,
            jsonb_build_object('status', NEW.status, 'credential_id', NEW.credential_id,
                               'credential_type', NEW.credential_type));
    ELSIF NEW.provision_error IS DISTINCT FROM OLD.provision_error AND NEW.provision_error IS NOT NULL THEN
        PERFORM public.complete_coordinator_link('credential_request:' || NEW.id::text,
            jsonb_build_object('status', CASE WHEN NEW.status='provisioning' THEN 'uncertain' ELSE 'failed' END,
                               'credential_type', NEW.credential_type, 'error', NEW.provision_error));
    END IF;
    RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION public.credential_request_complete_link() FROM PUBLIC, anon, authenticated;
CREATE TRIGGER credential_request_complete_link AFTER UPDATE ON public.credential_requests
    FOR EACH ROW EXECUTE FUNCTION public.credential_request_complete_link();

-- Existing approval links get the same transaction guarantee at the lifecycle
-- boundary, rather than relying on each human-decision endpoint to enqueue it.
CREATE FUNCTION public.credential_approval_complete_link() RETURNS trigger
LANGUAGE plpgsql SET search_path = '' AS $$
DECLARE p jsonb := NEW.action_payload;
BEGIN
    IF NEW.credential_id IS NOT NULL AND NEW.status IN ('approved','rejected')
       AND NEW.status IS DISTINCT FROM OLD.status AND p->'continuation' IS NOT NULL
       AND p->'continuation' <> 'null'::jsonb
       AND p->>'conversation_id' = 'coordinator:' || (p->>'caller_user_id') THEN
        INSERT INTO public.coordinator_wakeups(user_id,source,source_id,context,payload,send_to_phone)
        VALUES ((p->>'caller_user_id')::uuid,'credential_approval',NEW.id,p->'continuation',
            jsonb_build_object('approval_id',NEW.id,'status',NEW.status,'credential_id',NEW.credential_id,
                               'node_type',p->>'node_type','operation',p->>'operation','arguments',p->'arguments'),
            COALESCE(p->'continuation'->>'channel','web') <> 'web')
        ON CONFLICT(source,source_id) DO NOTHING;
    END IF;
    RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION public.credential_approval_complete_link() FROM PUBLIC, anon, authenticated;
CREATE TRIGGER credential_approval_complete_link AFTER UPDATE OF status ON public.approval_requests
    FOR EACH ROW EXECUTE FUNCTION public.credential_approval_complete_link();
