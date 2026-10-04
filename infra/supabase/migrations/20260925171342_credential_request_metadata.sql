-- Options the minting surface sets on one request: where the provide page
-- returns the person (redirect_url), whether the requester is emailed
-- (notify_requester) and whether the request is listed (hidden_from_owner).
ALTER TABLE public.credential_requests ADD COLUMN metadata jsonb NOT NULL DEFAULT '{}'::jsonb;
