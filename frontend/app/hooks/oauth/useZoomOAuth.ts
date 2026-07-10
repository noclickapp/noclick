// Zoom OAuth — standard flow (comma-separated granular scopes). Built from the
// shared createOAuthHook factory; only the per-provider config lives here. The
// authorize route (/api/auth/zoom/authorize) splits the comma-separated scopes
// and space-joins them for Zoom's `scope` param.
import { createOAuthHook } from './createOAuthHook';

export const useZoomOAuth = createOAuthHook({
    provider: 'zoom',
    defaultScopes: [
        'meeting:read:meeting',
        'meeting:write:meeting',
        'meeting:read:list_meetings',
        'meeting:read:list_registrants',
        'meeting:write:registrant',
        'meeting:read:invitation',
        'meeting:read:past_meeting',
        'meeting:read:list_past_participants',
        'webinar:read:webinar',
        'webinar:write:webinar',
        'webinar:read:list_webinars',
        'webinar:read:list_registrants',
        'webinar:write:registrant',
        'user:read:user',
        'user:write:user',
        'user:read:list_users',
        'cloud_recording:read:list_user_recordings',
        'cloud_recording:read:list_account_recordings',
        'cloud_recording:read:list_recording_files',
        'cloud_recording:delete:meeting_recordings',
        'phone:read:list_call_logs',
        'chat_message:write:message',
    ],
});
