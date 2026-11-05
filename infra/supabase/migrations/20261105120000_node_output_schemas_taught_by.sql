-- What taught each learned output shape: 'delivery' (a trigger's delivery as it arrived), 'run' (a node's output),
-- NULL on a row from before this was recorded, whose source can't be told.
ALTER TABLE public.workflow_node_output_schemas ADD COLUMN IF NOT EXISTS taught_by text
    CHECK (taught_by IN ('delivery', 'run'));

-- The delivery's own plumbing is on no node's output (those are keyed by step), so a row holding it came from one.
UPDATE public.workflow_node_output_schemas SET taught_by = 'delivery'
WHERE taught_by IS NULL AND output_schema ? '_webhook';
