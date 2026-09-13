-- A thread interchange that fails to translate reports itself as feedback
-- (nodes/agent/session_interchange.py:report_fallback, type
-- 'interchange_fallback'); the CHECK enumerates types, so every report
-- bounced on user_feedback_type_check (2026-09-13 E2E).
ALTER TABLE public.user_feedback
    DROP CONSTRAINT IF EXISTS user_feedback_type_check;
ALTER TABLE public.user_feedback
    ADD CONSTRAINT user_feedback_type_check
    CHECK (type IN ('bug', 'idea', 'general', 'agent_bug', 'interchange_fallback'));
