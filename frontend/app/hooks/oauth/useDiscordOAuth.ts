// Discord OAuth — built from the shared createOAuthHook factory (config only).
import { createOAuthHook } from './createOAuthHook';

export const useDiscordOAuth = createOAuthHook({
    provider: 'discord',
    defaultScopes: ['identify', 'email', 'guilds'],
});
