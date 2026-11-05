-- The nightly trigger resync's one row (utils/webhook_manager.py resync_trigger_registrations): whether it may
-- register and tear down at all, which a person turns on after reading its dry run, and the last workflow its lap
-- reached, by id. No row means it's off and no lap has started. after_workflow_id names no foreign key: a workflow
-- deleted under the lap changes nothing, the next id past it is still next.
-- Backend-only: RLS on with no policy, and the API roles hold no grants.
CREATE TABLE IF NOT EXISTS public.trigger_resync_state (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    registers boolean NOT NULL DEFAULT false,
    registers_set_at timestamptz,
    after_workflow_id uuid,
    lap_finished_at timestamptz,
    updated_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE public.trigger_resync_state ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.trigger_resync_state FROM anon, authenticated;
