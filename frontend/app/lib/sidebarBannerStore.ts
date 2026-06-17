// Coordinates the mutually-exclusive sidebar banners (InterruptedRunBanner +
// eligible banners) so only ONE shows at a time. Priority:
// the interrupted-run banner wins (a dead run is the most urgent thing to act
// on); then the invite banner; then quick-publish. Each banner publishes its
// visibility here and yields to any higher-priority one that's up.
import { proxy } from 'valtio';

export const sidebarBannerStore = proxy<{
    /** Whether the (highest-priority) interrupted-run banner is visible. */
    interruptedVisible: boolean;
    /** Whether the (higher-priority) invite banner is currently visible. */
    inviteVisible: boolean;
}>({
    interruptedVisible: false,
    inviteVisible: false,
});
