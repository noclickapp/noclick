// Coordinates the mutually-exclusive sidebar banners (eligible banners)
// so only ONE shows at a time. Priority: the invite banner takes the slot first; the
// quick-publish banner waits until the invite banner is gone (dismissed, opted out, or
// not armed), then takes over. InviteBanner publishes its visibility here; QuickPublishBanner
// reads it and yields the slot while the invite banner is up.
import { proxy } from 'valtio';

export const sidebarBannerStore = proxy<{
    /** Whether the (higher-priority) invite banner is currently visible. */
    inviteVisible: boolean;
}>({
    inviteVisible: false,
});
