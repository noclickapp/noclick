// Dropbox OAuth — built from the shared createOAuthHook factory (config only).
import { createOAuthHook } from './createOAuthHook';

export const useDropboxOAuth = createOAuthHook({
    provider: 'dropbox',
    defaultScopes: [
        'account_info.read',
        'files.metadata.read',
        'files.metadata.write',
        'files.content.read',
        'files.content.write',
        'sharing.read',
        'sharing.write',
        'file_requests.read',
        'file_requests.write',
    ],
});
