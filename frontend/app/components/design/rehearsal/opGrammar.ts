/* The operation grammar: how each trigger OPERATION renders inside its app's
   frame — the status pill in the app's own words, the activity byline, the
   caption, the glyph. Authored per app against the REAL x-is-trigger
   operation inventory (782 ops across the registry; every themed app's ops
   are covered explicitly), with a generic action lexicon as the fallback for
   operations the tables don't name. The bespoke frames consume this instead
   of ad-hoc keyword regexes, so `on_issue_pinned` says "pinned by …" with a
   pin glyph rather than defaulting to a green Open card. */

export type PillTone = 'good' | 'bad' | 'warn' | 'info' | 'neutral' | 'brand';

export type IconKey =
    | 'issue' | 'pr' | 'merge' | 'commit' | 'tag' | 'star' | 'comment' | 'edit'
    | 'label' | 'pin' | 'lock' | 'milestone' | 'trash' | 'user' | 'users'
    | 'alert' | 'check' | 'calendar' | 'file' | 'card' | 'bell' | 'mail'
    | 'phone' | 'video' | 'form' | 'cart' | 'dollar' | 'refresh' | 'eye' | 'shield';

export interface OpRender {
    /** Status pill in the app's own words. */
    pill?: { label: string; tone: PillTone };
    /** Byline phrase; '{author}' is replaced with the staged sender. */
    byline?: string;
    /** Uppercase eyebrow caption for caption-led cards. */
    caption?: string;
    /** Leading glyph override. */
    icon?: IconKey;
}

/** Semantic tone → hue on a dark app surface. 'brand'/'neutral' resolve
    against the theme at render time. */
export const TONE_HUES: Record<Exclude<PillTone, 'brand' | 'neutral'>, string> = {
    good: '#4ecf7f',
    bad: '#f2716a',
    warn: '#e8b34b',
    info: '#5297ff',
};

/* ======================================================================
   Per-app tables — keys are the EXACT operation constants from the node
   schemas. Authored in each app's own interface vocabulary.
   ====================================================================== */

// GitHub — activity-feed vocabulary: Open / Closed / Merged / Draft, stars,
// releases, pushes. (Merged renders purple — the frame owns that hue.)
const GITHUB_OPS: Record<string, OpRender> = {
    on_issue_assigned: { pill: { label: 'Open', tone: 'good' }, byline: 'assigned by {author}', icon: 'user' },
    on_issue_closed: { pill: { label: 'Closed', tone: 'bad' }, byline: 'closed by {author}', icon: 'issue' },
    on_issue_comment: { pill: { label: 'Open', tone: 'good' }, byline: '{author} commented', icon: 'comment' },
    on_issue_deleted: { pill: { label: 'Deleted', tone: 'bad' }, byline: 'deleted by {author}', icon: 'trash' },
    on_issue_demilestoned: { pill: { label: 'Open', tone: 'good' }, byline: 'removed from milestone by {author}', icon: 'milestone' },
    on_issue_edited: { pill: { label: 'Open', tone: 'good' }, byline: 'edited by {author}', icon: 'edit' },
    on_issue_labeled: { pill: { label: 'Open', tone: 'good' }, byline: 'labeled by {author}', icon: 'label' },
    on_issue_locked: { pill: { label: 'Locked', tone: 'warn' }, byline: 'locked by {author}', icon: 'lock' },
    on_issue_milestoned: { pill: { label: 'Open', tone: 'good' }, byline: 'added to milestone by {author}', icon: 'milestone' },
    on_issue_opened: { pill: { label: 'Open', tone: 'good' }, byline: 'opened by {author}', icon: 'issue' },
    on_issue_pinned: { pill: { label: 'Open', tone: 'good' }, byline: 'pinned by {author}', icon: 'pin' },
    on_issue_reopened: { pill: { label: 'Reopened', tone: 'good' }, byline: 'reopened by {author}', icon: 'issue' },
    on_issue_transferred: { pill: { label: 'Transferred', tone: 'neutral' }, byline: 'transferred by {author}', icon: 'issue' },
    on_issue_unassigned: { pill: { label: 'Open', tone: 'good' }, byline: 'unassigned by {author}', icon: 'user' },
    on_issue_unlabeled: { pill: { label: 'Open', tone: 'good' }, byline: 'label removed by {author}', icon: 'label' },
    on_issue_unlocked: { pill: { label: 'Open', tone: 'good' }, byline: 'unlocked by {author}', icon: 'lock' },
    on_issue_unpinned: { pill: { label: 'Open', tone: 'good' }, byline: 'unpinned by {author}', icon: 'pin' },
    on_pull_request_assigned: { pill: { label: 'Open', tone: 'good' }, byline: 'assigned by {author}', icon: 'user' },
    on_pull_request_auto_merge_disabled: { pill: { label: 'Open', tone: 'good' }, byline: 'auto-merge disabled by {author}', icon: 'merge' },
    on_pull_request_auto_merge_enabled: { pill: { label: 'Open', tone: 'good' }, byline: 'auto-merge enabled by {author}', icon: 'merge' },
    on_pull_request_closed: { pill: { label: 'Closed', tone: 'bad' }, byline: 'closed by {author}', icon: 'pr' },
    on_pull_request_converted_to_draft: { pill: { label: 'Draft', tone: 'neutral' }, byline: 'converted to draft by {author}', icon: 'pr' },
    on_pull_request_demilestoned: { pill: { label: 'Open', tone: 'good' }, byline: 'removed from milestone by {author}', icon: 'milestone' },
    on_pull_request_dequeued: { pill: { label: 'Open', tone: 'good' }, byline: 'removed from the merge queue', icon: 'merge' },
    on_pull_request_edited: { pill: { label: 'Open', tone: 'good' }, byline: 'edited by {author}', icon: 'edit' },
    on_pull_request_enqueued: { pill: { label: 'Queued to merge', tone: 'info' }, byline: 'added to the merge queue by {author}', icon: 'merge' },
    on_pull_request_labeled: { pill: { label: 'Open', tone: 'good' }, byline: 'labeled by {author}', icon: 'label' },
    on_pull_request_locked: { pill: { label: 'Locked', tone: 'warn' }, byline: 'locked by {author}', icon: 'lock' },
    on_pull_request_merged: { pill: { label: 'Merged', tone: 'info' }, byline: 'merged by {author}', icon: 'merge' },
    on_pull_request_milestoned: { pill: { label: 'Open', tone: 'good' }, byline: 'added to milestone by {author}', icon: 'milestone' },
    on_pull_request_opened: { pill: { label: 'Open', tone: 'good' }, byline: 'opened by {author}', icon: 'pr' },
    on_pull_request_ready_for_review: { pill: { label: 'Open', tone: 'good' }, byline: 'marked ready for review by {author}', icon: 'pr' },
    on_pull_request_reopened: { pill: { label: 'Reopened', tone: 'good' }, byline: 'reopened by {author}', icon: 'pr' },
    on_pull_request_review_request_removed: { pill: { label: 'Open', tone: 'good' }, byline: '{author} removed a review request', icon: 'eye' },
    on_pull_request_review_requested: { pill: { label: 'Review requested', tone: 'warn' }, byline: '{author} requested review', icon: 'eye' },
    on_pull_request_synchronize: { pill: { label: 'Open', tone: 'good' }, byline: '{author} pushed new commits', icon: 'commit' },
    on_pull_request_unassigned: { pill: { label: 'Open', tone: 'good' }, byline: 'unassigned by {author}', icon: 'user' },
    on_pull_request_unlabeled: { pill: { label: 'Open', tone: 'good' }, byline: 'label removed by {author}', icon: 'label' },
    on_pull_request_unlocked: { pill: { label: 'Open', tone: 'good' }, byline: 'unlocked by {author}', icon: 'lock' },
    on_push: { pill: { label: 'Pushed', tone: 'info' }, byline: '{author} pushed to the branch', icon: 'commit' },
    on_release_created: { pill: { label: 'Draft', tone: 'neutral' }, byline: 'release created by {author}', icon: 'tag' },
    on_release_deleted: { pill: { label: 'Deleted', tone: 'bad' }, byline: 'release deleted by {author}', icon: 'trash' },
    on_release_edited: { pill: { label: 'Published', tone: 'good' }, byline: 'release edited by {author}', icon: 'edit' },
    on_release_prereleased: { pill: { label: 'Pre-release', tone: 'warn' }, byline: 'pre-release published by {author}', icon: 'tag' },
    on_release_published: { pill: { label: 'Published', tone: 'good' }, byline: 'release published by {author}', icon: 'tag' },
    on_release_released: { pill: { label: 'Latest', tone: 'good' }, byline: 'release marked latest by {author}', icon: 'tag' },
    on_release_unpublished: { pill: { label: 'Draft', tone: 'neutral' }, byline: 'release unpublished by {author}', icon: 'tag' },
    on_star_created: { pill: { label: 'Starred', tone: 'warn' }, byline: 'starred by {author}', icon: 'star' },
    on_star_deleted: { pill: { label: 'Unstarred', tone: 'neutral' }, byline: 'unstarred by {author}', icon: 'star' },
};

// GitLab — generic webhook envelopes; the payload names the real action.
const GITLAB_OPS: Record<string, OpRender> = {
    on_group_event: { pill: { label: 'Event', tone: 'info' }, byline: 'activity in the group', icon: 'users' },
    on_project_event: { pill: { label: 'Event', tone: 'info' }, byline: 'activity in the project', icon: 'commit' },
};

// Linear — workflow states: Todo (brand), Done, Canceled.
const LINEAR_OPS: Record<string, OpRender> = {
    on_comment_created: { byline: '{author} commented', icon: 'comment' },
    on_comment_deleted: { pill: { label: 'Deleted', tone: 'bad' }, byline: 'comment deleted by {author}', icon: 'trash' },
    on_comment_updated: { byline: 'comment edited by {author}', icon: 'comment' },
    on_issue_created: { pill: { label: 'Todo', tone: 'brand' }, byline: 'created by {author}', icon: 'issue' },
    on_issue_deleted: { pill: { label: 'Deleted', tone: 'bad' }, byline: 'deleted by {author}', icon: 'trash' },
    on_issue_updated: { pill: { label: 'Todo', tone: 'brand' }, byline: 'updated by {author}', icon: 'edit' },
    on_project_created: { pill: { label: 'Todo', tone: 'brand' }, byline: 'project created by {author}', icon: 'milestone' },
    on_project_deleted: { pill: { label: 'Deleted', tone: 'bad' }, byline: 'project deleted by {author}', icon: 'trash' },
    on_project_updated: { pill: { label: 'Todo', tone: 'brand' }, byline: 'project updated by {author}', icon: 'edit' },
};

// Jira — status lozenges: TO DO (blue), DONE (green).
const JIRA_OPS: Record<string, OpRender> = {
    on_comment_added: { pill: { label: 'TO DO', tone: 'info' }, byline: '{author} added a comment', icon: 'comment' },
    on_issue_created: { pill: { label: 'TO DO', tone: 'info' }, byline: 'created by {author}', icon: 'issue' },
    on_issue_deleted: { pill: { label: 'Deleted', tone: 'bad' }, byline: 'deleted by {author}', icon: 'trash' },
    on_issue_updated: { pill: { label: 'TO DO', tone: 'info' }, byline: 'updated by {author}', icon: 'edit' },
};

// Sentry — issues arrive Unresolved.
const SENTRY_OPS: Record<string, OpRender> = {
    on_alert: { caption: 'Alert', pill: { label: 'Unresolved', tone: 'bad' }, byline: 'alert rule fired', icon: 'alert' },
    on_error: { caption: 'Error', pill: { label: 'Unresolved', tone: 'bad' }, byline: 'new error event captured', icon: 'alert' },
};

// Datadog — monitors go into Alert state when they trigger.
const DATADOG_OPS: Record<string, OpRender> = {
    on_new_event: { caption: 'Monitor', pill: { label: 'Alert', tone: 'bad' }, byline: 'monitor triggered', icon: 'alert' },
};

// PagerDuty — incident lifecycle: Triggered / Acknowledged / Resolved.
const PAGERDUTY_OPS: Record<string, OpRender> = {
    on_incident_event: { caption: 'Incident', pill: { label: 'Triggered', tone: 'bad' }, byline: 'incident triggered', icon: 'alert' },
};

// Firestore — document writes; no state pill.
const FIRESTORE_OPS: Record<string, OpRender> = {
    on_document_changed: { byline: 'document written', icon: 'file' },
};

/* ======================================================================
   Registry + resolution
   ====================================================================== */

// Stripe — dashboard vocabulary: Succeeded / Failed / Past due / Uncollectible
// / Voided / Requires action; captions name the object.
const STRIPE_OPS: Record<string, OpRender> = {
    on_account_application_deauthorized: { caption: 'Account', pill: { label: 'Disconnected', tone: 'bad' }, byline: 'application was deauthorized', icon: 'shield' },
    on_account_updated: { caption: 'Account', pill: { label: 'Updated', tone: 'info' }, byline: 'account details were updated', icon: 'user' },
    on_charge_captured: { caption: 'Payment', pill: { label: 'Captured', tone: 'good' }, byline: 'the payment was captured', icon: 'card' },
    on_charge_failed: { caption: 'Payment', pill: { label: 'Failed', tone: 'bad' }, byline: 'the payment failed', icon: 'card' },
    on_charge_refunded: { caption: 'Refund', pill: { label: 'Refunded', tone: 'info' }, byline: 'the payment was refunded', icon: 'refresh' },
    on_charge_succeeded: { caption: 'Payment', pill: { label: 'Succeeded', tone: 'good' }, byline: '{author} paid', icon: 'dollar' },
    on_charge_updated: { caption: 'Payment', pill: { label: 'Updated', tone: 'neutral' }, byline: 'the payment was updated', icon: 'card' },
    on_checkout_session_async_payment_failed: { caption: 'Checkout', pill: { label: 'Failed', tone: 'bad' }, byline: 'the delayed payment failed', icon: 'cart' },
    on_checkout_session_async_payment_succeeded: { caption: 'Checkout', pill: { label: 'Succeeded', tone: 'good' }, byline: 'the delayed payment succeeded', icon: 'cart' },
    on_checkout_session_completed: { caption: 'Checkout', pill: { label: 'Complete', tone: 'good' }, byline: '{author} completed checkout', icon: 'cart' },
    on_checkout_session_expired: { caption: 'Checkout', pill: { label: 'Expired', tone: 'bad' }, byline: 'the checkout session expired', icon: 'cart' },
    on_customer_created: { caption: 'Customer', pill: { label: 'Created', tone: 'info' }, byline: '{author} became a customer', icon: 'user' },
    on_customer_deleted: { caption: 'Customer', pill: { label: 'Deleted', tone: 'bad' }, byline: '{author} was deleted', icon: 'user' },
    on_customer_updated: { caption: 'Customer', pill: { label: 'Updated', tone: 'neutral' }, byline: '{author} was updated', icon: 'user' },
    on_charge_dispute_closed: { caption: 'Dispute', pill: { label: 'Closed', tone: 'neutral' }, byline: 'the dispute was closed', icon: 'shield' },
    on_charge_dispute_created: { caption: 'Dispute', pill: { label: 'Needs response', tone: 'bad' }, byline: '{author} disputed a payment', icon: 'alert' },
    on_charge_dispute_funds_withdrawn: { caption: 'Dispute', pill: { label: 'Funds withdrawn', tone: 'bad' }, byline: 'the disputed funds were withdrawn', icon: 'alert' },
    on_charge_dispute_updated: { caption: 'Dispute', pill: { label: 'Updated', tone: 'warn' }, byline: 'the dispute was updated', icon: 'shield' },
    on_event: { caption: 'Event', pill: { label: 'Received', tone: 'neutral' }, byline: 'a Stripe event was received', icon: 'refresh' },
    on_invoice_created: { caption: 'Invoice', pill: { label: 'Draft', tone: 'neutral' }, byline: 'an invoice was created', icon: 'file' },
    on_invoice_finalized: { caption: 'Invoice', pill: { label: 'Open', tone: 'info' }, byline: 'the invoice was finalized', icon: 'file' },
    on_invoice_paid: { caption: 'Invoice', pill: { label: 'Paid', tone: 'good' }, byline: '{author} paid the invoice', icon: 'dollar' },
    on_invoice_payment_action_required: { caption: 'Invoice', pill: { label: 'Requires action', tone: 'warn' }, byline: 'the payment needs customer authentication', icon: 'alert' },
    on_invoice_payment_failed: { caption: 'Invoice', pill: { label: 'Past due', tone: 'bad' }, byline: 'the invoice payment failed', icon: 'alert' },
    on_invoice_payment_succeeded: { caption: 'Invoice', pill: { label: 'Paid', tone: 'good' }, byline: 'the invoice payment succeeded', icon: 'dollar' },
    on_invoice_marked_uncollectible: { caption: 'Invoice', pill: { label: 'Uncollectible', tone: 'bad' }, byline: 'the invoice was marked uncollectible', icon: 'alert' },
    on_invoice_upcoming: { caption: 'Invoice', pill: { label: 'Upcoming', tone: 'warn' }, byline: 'an invoice is coming up', icon: 'calendar' },
    on_invoice_voided: { caption: 'Invoice', pill: { label: 'Voided', tone: 'bad' }, byline: 'the invoice was voided', icon: 'file' },
    on_payment_intent_payment_failed: { caption: 'Payment', pill: { label: 'Failed', tone: 'bad' }, byline: 'the payment failed', icon: 'card' },
    on_payment_intent_canceled: { caption: 'Payment', pill: { label: 'Canceled', tone: 'bad' }, byline: 'the payment was canceled', icon: 'card' },
    on_payment_intent_created: { caption: 'Payment', pill: { label: 'Incomplete', tone: 'neutral' }, byline: 'a payment was started', icon: 'card' },
    on_payment_method_attached: { caption: 'Customer', pill: { label: 'Card added', tone: 'good' }, byline: '{author} added a payment method', icon: 'card' },
    on_payment_method_detached: { caption: 'Customer', pill: { label: 'Card removed', tone: 'warn' }, byline: '{author} removed a payment method', icon: 'card' },
    on_payment_intent_processing: { caption: 'Payment', pill: { label: 'Processing', tone: 'warn' }, byline: 'the payment is processing', icon: 'refresh' },
    on_payment_intent_requires_action: { caption: 'Payment', pill: { label: 'Requires action', tone: 'warn' }, byline: 'the payment needs customer authentication', icon: 'alert' },
    on_payment_intent_succeeded: { caption: 'Payment', pill: { label: 'Succeeded', tone: 'good' }, byline: '{author} paid', icon: 'dollar' },
    on_payout_created: { caption: 'Payout', pill: { label: 'In transit', tone: 'warn' }, byline: 'a payout was created', icon: 'dollar' },
    on_payout_failed: { caption: 'Payout', pill: { label: 'Failed', tone: 'bad' }, byline: 'the payout failed', icon: 'alert' },
    on_payout_paid: { caption: 'Payout', pill: { label: 'Paid', tone: 'good' }, byline: 'the payout landed in your bank', icon: 'dollar' },
    on_price_created: { caption: 'Price', pill: { label: 'Created', tone: 'info' }, byline: 'a price was created', icon: 'dollar' },
    on_price_updated: { caption: 'Price', pill: { label: 'Updated', tone: 'neutral' }, byline: 'a price was updated', icon: 'dollar' },
    on_product_created: { caption: 'Product', pill: { label: 'Created', tone: 'info' }, byline: 'a product was created', icon: 'cart' },
    on_product_deleted: { caption: 'Product', pill: { label: 'Deleted', tone: 'bad' }, byline: 'a product was deleted', icon: 'trash' },
    on_product_updated: { caption: 'Product', pill: { label: 'Updated', tone: 'neutral' }, byline: 'a product was updated', icon: 'cart' },
    on_quote_accepted: { caption: 'Quote', pill: { label: 'Accepted', tone: 'good' }, byline: '{author} accepted the quote', icon: 'file' },
    on_charge_refund_updated: { caption: 'Refund', pill: { label: 'Updated', tone: 'neutral' }, byline: 'the refund was updated', icon: 'refresh' },
    on_review_closed: { caption: 'Review', pill: { label: 'Closed', tone: 'good' }, byline: 'the Radar review was closed', icon: 'eye' },
    on_review_opened: { caption: 'Review', pill: { label: 'Open', tone: 'warn' }, byline: 'Radar flagged a payment for review', icon: 'eye' },
    on_setup_intent_setup_failed: { caption: 'Setup', pill: { label: 'Failed', tone: 'bad' }, byline: 'saving the payment method failed', icon: 'card' },
    on_setup_intent_succeeded: { caption: 'Setup', pill: { label: 'Succeeded', tone: 'good' }, byline: '{author} saved a payment method', icon: 'card' },
    on_customer_subscription_created: { caption: 'Subscription', pill: { label: 'Active', tone: 'good' }, byline: '{author} subscribed', icon: 'refresh' },
    on_customer_subscription_deleted: { caption: 'Subscription', pill: { label: 'Canceled', tone: 'bad' }, byline: '{author} canceled their subscription', icon: 'refresh' },
    on_customer_subscription_paused: { caption: 'Subscription', pill: { label: 'Paused', tone: 'warn' }, byline: '{author} paused their subscription', icon: 'refresh' },
    on_customer_subscription_resumed: { caption: 'Subscription', pill: { label: 'Active', tone: 'good' }, byline: '{author} resumed their subscription', icon: 'refresh' },
    on_customer_subscription_trial_will_end: { caption: 'Subscription', pill: { label: 'Trial ending', tone: 'warn' }, byline: 'the trial ends soon', icon: 'calendar' },
    on_customer_subscription_updated: { caption: 'Subscription', pill: { label: 'Updated', tone: 'neutral' }, byline: 'the subscription was updated', icon: 'refresh' },
};

const SHOPIFY_OPS: Record<string, OpRender> = {
    on_customer_created: { pill: { label: 'New customer', tone: 'info' }, byline: '{author} created an account', icon: 'user' },
    on_order_cancelled: { pill: { label: 'Cancelled', tone: 'bad' }, byline: '{author} cancelled the order', icon: 'cart' },
    on_order_created: { pill: { label: 'New order', tone: 'good' }, byline: '{author} placed an order', icon: 'cart' },
    on_order_fulfilled: { pill: { label: 'Fulfilled', tone: 'good' }, byline: 'the order was fulfilled', icon: 'check' },
    on_order_paid: { pill: { label: 'Paid', tone: 'good' }, byline: '{author} paid for the order', icon: 'dollar' },
    on_product_created: { pill: { label: 'Added', tone: 'info' }, byline: 'a product was added', icon: 'cart' },
    on_product_updated: { pill: { label: 'Updated', tone: 'neutral' }, byline: 'a product was updated', icon: 'edit' },
};

const ZOOM_OPS: Record<string, OpRender> = {
    on_account_created: { pill: { label: 'Created', tone: 'info' }, byline: 'a sub account was created', icon: 'users' },
    on_account_disassociated: { pill: { label: 'Disassociated', tone: 'warn' }, byline: 'a sub account was disassociated', icon: 'users' },
    on_account_settings_updated: { byline: 'account settings were updated', icon: 'shield' },
    on_account_updated: { byline: 'the account profile was updated', icon: 'users' },
    on_account_vanity_url_updated: { byline: 'the vanity URL was updated', icon: 'edit' },
    on_any_zoom_event: { pill: { label: 'Any event', tone: 'neutral' }, byline: 'a Zoom event was received', icon: 'bell' },
    on_chat_channel_created: { pill: { label: 'Created', tone: 'info' }, byline: '{author} created a channel', icon: 'comment' },
    on_chat_channel_deleted: { pill: { label: 'Deleted', tone: 'bad' }, byline: '{author} deleted a channel', icon: 'trash' },
    on_chat_channel_member_invited: { byline: '{author} was invited to the channel', icon: 'user' },
    on_chat_channel_member_joined: { byline: '{author} joined the channel', icon: 'user' },
    on_chat_channel_member_left: { byline: '{author} left the channel', icon: 'user' },
    on_chat_channel_updated: { byline: '{author} updated the channel', icon: 'comment' },
    on_chat_message_deleted: { pill: { label: 'Deleted', tone: 'bad' }, byline: '{author} deleted a message', icon: 'trash' },
    on_chat_message_sent: { byline: '{author} sent a message', icon: 'comment' },
    on_chat_message_updated: { byline: '{author} edited a message', icon: 'edit' },
    on_meeting_alert: { pill: { label: 'Alert', tone: 'warn' }, byline: 'a meeting alert was raised', icon: 'alert' },
    on_meeting_breakout_room_ended: { pill: { label: 'Ended', tone: 'neutral' }, byline: 'breakout rooms ended', icon: 'users' },
    on_meeting_breakout_room_started: { pill: { label: 'Started', tone: 'good' }, byline: 'breakout rooms started', icon: 'users' },
    on_meeting_chat_message_sent: { byline: '{author} sent a message in the meeting', icon: 'comment' },
    on_meeting_created: { pill: { label: 'Scheduled', tone: 'info' }, byline: '{author} scheduled a meeting', icon: 'calendar' },
    on_meeting_deleted: { pill: { label: 'Deleted', tone: 'bad' }, byline: '{author} deleted the meeting', icon: 'trash' },
    on_meeting_ended: { pill: { label: 'Ended', tone: 'neutral' }, byline: 'the meeting ended', icon: 'video' },
    on_meeting_live_streaming_started: { pill: { label: 'Live', tone: 'good' }, byline: 'live streaming started', icon: 'video' },
    on_meeting_live_streaming_stopped: { pill: { label: 'Stopped', tone: 'neutral' }, byline: 'live streaming stopped', icon: 'video' },
    on_meeting_participant_admitted: { pill: { label: 'Admitted', tone: 'good' }, byline: '{author} was admitted to the meeting', icon: 'user' },
    on_meeting_participant_jbh_joined: { byline: '{author} joined before the host', icon: 'user' },
    on_meeting_participant_jbh_waiting: { pill: { label: 'Waiting for host', tone: 'warn' }, byline: '{author} is waiting for the host', icon: 'user' },
    on_meeting_participant_joined: { byline: '{author} joined the meeting', icon: 'user' },
    on_meeting_participant_joined_waiting_room: { pill: { label: 'Waiting room', tone: 'warn' }, byline: '{author} entered the waiting room', icon: 'user' },
    on_meeting_participant_left: { byline: '{author} left the meeting', icon: 'user' },
    on_meeting_participant_left_waiting_room: { byline: '{author} left the waiting room', icon: 'user' },
    on_meeting_participant_put_in_waiting_room: { pill: { label: 'Waiting room', tone: 'warn' }, byline: '{author} was moved to the waiting room', icon: 'user' },
    on_meeting_participant_role_changed: { byline: "{author}'s role changed", icon: 'user' },
    on_meeting_permanently_deleted: { pill: { label: 'Permanently deleted', tone: 'bad' }, byline: 'the meeting was permanently deleted', icon: 'trash' },
    on_meeting_registration_approved: { pill: { label: 'Approved', tone: 'good' }, byline: "{author}'s registration was approved", icon: 'check' },
    on_meeting_registration_cancelled: { pill: { label: 'Cancelled', tone: 'bad' }, byline: '{author} cancelled their registration', icon: 'form' },
    on_meeting_registration_created: { pill: { label: 'Registered', tone: 'info' }, byline: '{author} registered for the meeting', icon: 'form' },
    on_meeting_registration_denied: { pill: { label: 'Denied', tone: 'bad' }, byline: "{author}'s registration was denied", icon: 'form' },
    on_meeting_risk_alert: { pill: { label: 'Risk alert', tone: 'bad' }, byline: 'a meeting risk was detected', icon: 'shield' },
    on_meeting_sharing_ended: { pill: { label: 'Ended', tone: 'neutral' }, byline: '{author} stopped sharing their screen', icon: 'video' },
    on_meeting_sharing_started: { pill: { label: 'Sharing', tone: 'good' }, byline: '{author} started sharing their screen', icon: 'video' },
    on_meeting_started: { pill: { label: 'Started', tone: 'good' }, byline: 'the meeting started', icon: 'video' },
    on_meeting_summary_completed: { pill: { label: 'Ready', tone: 'good' }, byline: 'the meeting summary is ready', icon: 'file' },
    on_meeting_updated: { byline: 'the meeting was updated', icon: 'edit' },
    on_phone_callee_answered: { pill: { label: 'Answered', tone: 'good' }, byline: '{author} answered the call', icon: 'phone' },
    on_phone_callee_ended: { pill: { label: 'Ended', tone: 'neutral' }, byline: 'the call ended', icon: 'phone' },
    on_phone_callee_missed: { pill: { label: 'Missed', tone: 'bad' }, byline: '{author} missed a call', icon: 'phone' },
    on_phone_callee_rejected: { pill: { label: 'Declined', tone: 'bad' }, byline: '{author} declined the call', icon: 'phone' },
    on_phone_caller_connected: { pill: { label: 'Connected', tone: 'good' }, byline: 'the call connected', icon: 'phone' },
    on_phone_caller_ended: { pill: { label: 'Ended', tone: 'neutral' }, byline: '{author} ended the call', icon: 'phone' },
    on_phone_emergency_alert: { pill: { label: 'Emergency', tone: 'bad' }, byline: 'an emergency call was placed', icon: 'alert' },
    on_phone_recording_completed: { pill: { label: 'Ready', tone: 'good' }, byline: 'the call recording is ready', icon: 'video' },
    on_phone_recording_started: { pill: { label: 'Recording', tone: 'good' }, byline: 'call recording started', icon: 'video' },
    on_phone_recording_stopped: { pill: { label: 'Stopped', tone: 'neutral' }, byline: 'call recording stopped', icon: 'video' },
    on_phone_sms_received: { byline: '{author} sent a text message', icon: 'comment' },
    on_phone_sms_sent: { byline: 'a text message was sent', icon: 'comment' },
    on_phone_voicemail_received: { pill: { label: 'New voicemail', tone: 'info' }, byline: '{author} left a voicemail', icon: 'phone' },
    on_phone_voicemail_transcript_completed: { pill: { label: 'Ready', tone: 'good' }, byline: 'the voicemail transcript is ready', icon: 'file' },
    on_recording_batch_deleted: { pill: { label: 'Deleted', tone: 'bad' }, byline: 'recordings were deleted', icon: 'trash' },
    on_recording_completed: { pill: { label: 'Ready', tone: 'good' }, byline: 'the recording is ready', icon: 'video' },
    on_recording_deleted: { pill: { label: 'Deleted', tone: 'bad' }, byline: 'the recording was deleted', icon: 'trash' },
    on_recording_paused: { pill: { label: 'Paused', tone: 'warn' }, byline: 'recording paused', icon: 'video' },
    on_recording_recovered: { pill: { label: 'Recovered', tone: 'good' }, byline: 'the recording was recovered from the trash', icon: 'refresh' },
    on_recording_registration_approved: { pill: { label: 'Approved', tone: 'good' }, byline: "{author}'s recording access was approved", icon: 'check' },
    on_recording_registration_created: { pill: { label: 'Registered', tone: 'info' }, byline: '{author} registered to view the recording', icon: 'form' },
    on_recording_resumed: { pill: { label: 'Recording', tone: 'good' }, byline: 'recording resumed', icon: 'video' },
    on_recording_started: { pill: { label: 'Recording', tone: 'good' }, byline: 'recording started', icon: 'video' },
    on_recording_stopped: { pill: { label: 'Stopped', tone: 'neutral' }, byline: 'recording stopped', icon: 'video' },
    on_recording_transcript_completed: { pill: { label: 'Ready', tone: 'good' }, byline: 'the recording transcript is ready', icon: 'file' },
    on_recording_trashed: { pill: { label: 'In trash', tone: 'warn' }, byline: 'the recording was moved to the trash', icon: 'trash' },
    on_user_activated: { pill: { label: 'Active', tone: 'good' }, byline: '{author} was activated', icon: 'user' },
    on_user_created: { pill: { label: 'Created', tone: 'info' }, byline: '{author} was added to the account', icon: 'user' },
    on_user_deactivated: { pill: { label: 'Deactivated', tone: 'warn' }, byline: '{author} was deactivated', icon: 'user' },
    on_user_deleted: { pill: { label: 'Deleted', tone: 'bad' }, byline: '{author} was deleted', icon: 'trash' },
    on_user_disassociated: { pill: { label: 'Disassociated', tone: 'warn' }, byline: '{author} left the account', icon: 'user' },
    on_user_invitation_accepted: { pill: { label: 'Accepted', tone: 'good' }, byline: '{author} accepted the invitation', icon: 'check' },
    on_user_personal_notes_updated: { byline: '{author} updated their personal notes', icon: 'edit' },
    on_user_presence_status_updated: { byline: '{author} changed their status', icon: 'user' },
    on_user_settings_updated: { byline: '{author} updated their settings', icon: 'shield' },
    on_user_signed_in: { pill: { label: 'Signed in', tone: 'good' }, byline: '{author} signed in', icon: 'user' },
    on_user_signed_out: { pill: { label: 'Signed out', tone: 'neutral' }, byline: '{author} signed out', icon: 'user' },
    on_user_updated: { byline: "{author}'s profile was updated", icon: 'user' },
    on_webinar_alert: { pill: { label: 'Alert', tone: 'warn' }, byline: 'a webinar alert was raised', icon: 'alert' },
    on_webinar_created: { pill: { label: 'Scheduled', tone: 'info' }, byline: '{author} scheduled a webinar', icon: 'calendar' },
    on_webinar_deleted: { pill: { label: 'Deleted', tone: 'bad' }, byline: '{author} deleted the webinar', icon: 'trash' },
    on_webinar_ended: { pill: { label: 'Ended', tone: 'neutral' }, byline: 'the webinar ended', icon: 'video' },
    on_webinar_participant_joined: { byline: '{author} joined the webinar', icon: 'user' },
    on_webinar_participant_left: { byline: '{author} left the webinar', icon: 'user' },
    on_webinar_registration_approved: { pill: { label: 'Approved', tone: 'good' }, byline: "{author}'s registration was approved", icon: 'check' },
    on_webinar_registration_cancelled: { pill: { label: 'Cancelled', tone: 'bad' }, byline: '{author} cancelled their registration', icon: 'form' },
    on_webinar_registration_created: { pill: { label: 'Registered', tone: 'info' }, byline: '{author} registered for the webinar', icon: 'form' },
    on_webinar_registration_denied: { pill: { label: 'Denied', tone: 'bad' }, byline: "{author}'s registration was denied", icon: 'form' },
    on_webinar_sharing_ended: { pill: { label: 'Ended', tone: 'neutral' }, byline: '{author} stopped sharing their screen', icon: 'video' },
    on_webinar_sharing_started: { pill: { label: 'Sharing', tone: 'good' }, byline: '{author} started sharing their screen', icon: 'video' },
    on_webinar_started: { pill: { label: 'Started', tone: 'good' }, byline: 'the webinar started', icon: 'video' },
    on_webinar_updated: { byline: 'the webinar was updated', icon: 'edit' },
};

const CALENDLY_OPS: Record<string, OpRender> = {
    on_contact_created: { pill: { label: 'New contact', tone: 'info' }, byline: '{author} was added to contacts', icon: 'user' },
    on_contact_deleted: { pill: { label: 'Deleted', tone: 'bad' }, byline: '{author} was removed from contacts', icon: 'trash' },
    on_contact_updated: { pill: { label: 'Updated', tone: 'neutral' }, byline: "{author}'s contact details changed", icon: 'user' },
    on_invitee_canceled: { pill: { label: 'Canceled', tone: 'bad' }, byline: '{author} canceled', icon: 'calendar' },
    on_invitee_created: { pill: { label: 'Confirmed', tone: 'good' }, byline: '{author} booked a meeting', icon: 'calendar' },
    on_invitee_no_show_created: { pill: { label: 'No-show', tone: 'bad' }, byline: '{author} was marked a no-show', icon: 'calendar' },
    on_invitee_no_show_deleted: { pill: { label: 'Confirmed', tone: 'good' }, byline: "{author}'s no-show was undone", icon: 'calendar' },
    on_routing_form_submission_created: { pill: { label: 'Submitted', tone: 'info' }, byline: '{author} submitted a routing form', icon: 'form' },
};

const CAL_COM_OPS: Record<string, OpRender> = {
    on_booking_event: { pill: { label: 'Confirmed', tone: 'good' }, byline: '{author} booked a meeting', icon: 'calendar' },
};

const GOOGLE_CALENDAR_OPS: Record<string, OpRender> = {
    on_event_cancelled: { pill: { label: 'Canceled', tone: 'bad' }, byline: '{author} canceled the event', icon: 'calendar' },
    on_calendar_event: { pill: { label: 'Updated', tone: 'neutral' }, byline: 'a calendar event changed', icon: 'calendar' },
    on_event_created: { pill: { label: 'Confirmed', tone: 'good' }, byline: '{author} created an event', icon: 'calendar' },
    on_event_tentative: { pill: { label: 'Tentative', tone: 'warn' }, byline: '{author} marked the event tentative', icon: 'calendar' },
    on_event_updated: { pill: { label: 'Rescheduled', tone: 'warn' }, byline: '{author} updated the event', icon: 'calendar' },
};

const MAILGUN_OPS: Record<string, OpRender> = {
    on_accepted: { pill: { label: 'Accepted', tone: 'neutral' }, byline: 'the message was accepted for delivery', icon: 'mail' },
    on_clicked: { pill: { label: 'Clicked', tone: 'info' }, byline: '{author} clicked a link', icon: 'mail' },
    on_delivered: { pill: { label: 'Delivered', tone: 'good' }, byline: 'the message was delivered to {author}', icon: 'mail' },
    on_hard_bounce: { pill: { label: 'Hard bounce', tone: 'bad' }, byline: 'the message to {author} bounced permanently', icon: 'mail' },
    on_inbound_email: { pill: { label: 'Received', tone: 'info' }, byline: '{author} sent an email', icon: 'mail' },
    on_opened: { pill: { label: 'Opened', tone: 'info' }, byline: '{author} opened the message', icon: 'mail' },
    on_soft_bounce: { pill: { label: 'Soft bounce', tone: 'warn' }, byline: 'the message to {author} was temporarily rejected', icon: 'mail' },
    on_spam_complaint: { pill: { label: 'Spam complaint', tone: 'bad' }, byline: '{author} marked the message as spam', icon: 'mail' },
    on_unsubscribed: { pill: { label: 'Unsubscribed', tone: 'warn' }, byline: '{author} unsubscribed', icon: 'mail' },
};

const ZENDESK_OPS: Record<string, OpRender> = {
    on_any_ticket_event: { pill: { label: 'Ticket', tone: 'info' }, byline: 'ticket activity from {author}', icon: 'card' },
    on_organization_created: { caption: 'New organization', byline: 'added by {author}', icon: 'users' },
    on_organization_deleted: { pill: { label: 'Deleted', tone: 'bad' }, caption: 'Organization deleted', byline: 'removed by {author}', icon: 'trash' },
    on_ticket_agent_assignment_changed: { pill: { label: 'Open', tone: 'brand' }, byline: 'assigned to {author}', icon: 'user' },
    on_ticket_comment_added: { pill: { label: 'Open', tone: 'brand' }, byline: '{author} added a comment', icon: 'comment' },
    on_ticket_created: { pill: { label: 'New', tone: 'brand' }, byline: 'ticket submitted by {author}', icon: 'card' },
    on_ticket_csat_received: { pill: { label: 'Solved', tone: 'good' }, byline: 'CSAT rating received from {author}', icon: 'star' },
    on_ticket_custom_field_changed: { pill: { label: 'Open', tone: 'brand' }, byline: 'custom field updated by {author}', icon: 'edit' },
    on_ticket_custom_status_changed: { pill: { label: 'Status changed', tone: 'info' }, byline: '{author} changed the custom status', icon: 'refresh' },
    on_ticket_group_assignment_changed: { pill: { label: 'Open', tone: 'brand' }, byline: 'moved to another group by {author}', icon: 'users' },
    on_ticket_merged: { pill: { label: 'Merged', tone: 'neutral' }, byline: '{author} merged the ticket', icon: 'merge' },
    on_ticket_organization_changed: { pill: { label: 'Open', tone: 'brand' }, byline: 'organization changed by {author}', icon: 'users' },
    on_ticket_priority_changed: { pill: { label: 'Priority', tone: 'warn' }, byline: '{author} changed the priority', icon: 'alert' },
    on_ticket_requester_changed: { pill: { label: 'Open', tone: 'brand' }, byline: 'requester set to {author}', icon: 'user' },
    on_ticket_soft_deleted: { pill: { label: 'Deleted', tone: 'bad' }, byline: '{author} deleted the ticket', icon: 'trash' },
    on_ticket_status_changed: { pill: { label: 'Pending', tone: 'warn' }, byline: '{author} changed the status', icon: 'refresh' },
    on_ticket_subject_changed: { pill: { label: 'Open', tone: 'brand' }, byline: '{author} edited the subject', icon: 'edit' },
    on_ticket_tags_changed: { pill: { label: 'Open', tone: 'brand' }, byline: '{author} updated the tags', icon: 'label' },
    on_ticket_type_changed: { pill: { label: 'Open', tone: 'brand' }, byline: '{author} changed the ticket type', icon: 'label' },
    on_user_created: { caption: 'New user', byline: '{author} was added to Zendesk', icon: 'user' },
    on_user_deleted: { pill: { label: 'Deleted', tone: 'bad' }, caption: 'User deleted', byline: 'account removed', icon: 'trash' },
};

const INTERCOM_OPS: Record<string, OpRender> = {
    on_company_event: { caption: 'Company updated', byline: 'company record changed', icon: 'users' },
    on_contact_event: { caption: 'Contact updated', byline: '{author} updated in your contacts', icon: 'user' },
    on_conversation_event: { pill: { label: 'Open', tone: 'brand' }, byline: '{author} replied in the conversation', icon: 'comment' },
    on_ticket_event: { pill: { label: 'In progress', tone: 'info' }, byline: 'ticket updated by {author}', icon: 'card' },
};

const HUBSPOT_OPS: Record<string, OpRender> = {
    on_company_created: { caption: 'New company', byline: 'added to your CRM', icon: 'users' },
    on_contact_created: { caption: 'New contact', byline: '{author} was created', icon: 'user' },
    on_contact_deleted: { caption: 'Contact deleted', pill: { label: 'Deleted', tone: 'bad' }, byline: 'removed from your CRM', icon: 'trash' },
    on_contact_updated: { caption: 'Contact updated', byline: 'a property changed on {author}', icon: 'edit' },
    on_deal_created: { caption: 'New deal', pill: { label: 'Open', tone: 'brand' }, byline: 'created by {author}', icon: 'dollar' },
    on_deal_updated: { caption: 'Deal updated', byline: '{author} moved the deal stage', icon: 'dollar' },
    on_ticket_created: { caption: 'New ticket', pill: { label: 'New', tone: 'brand' }, byline: 'submitted by {author}', icon: 'card' },
};

const PIPEDRIVE_OPS: Record<string, OpRender> = {
    on_activity_changed: { caption: 'Activity updated', byline: '{author} updated the activity', icon: 'calendar' },
    on_activity_created: { caption: 'New activity', byline: 'scheduled by {author}', icon: 'calendar' },
    on_activity_deleted: { caption: 'Activity deleted', pill: { label: 'Deleted', tone: 'bad' }, byline: 'removed by {author}', icon: 'trash' },
    on_deal_changed: { caption: 'Deal updated', byline: '{author} updated the deal', icon: 'dollar' },
    on_deal_created: { caption: 'New deal', pill: { label: 'Open', tone: 'brand' }, byline: 'added by {author}', icon: 'dollar' },
    on_deal_deleted: { caption: 'Deal deleted', pill: { label: 'Deleted', tone: 'bad' }, byline: 'removed by {author}', icon: 'trash' },
    on_lead_changed: { caption: 'Lead updated', byline: '{author} updated the lead', icon: 'user' },
    on_lead_created: { caption: 'New lead', byline: 'added to the Leads Inbox by {author}', icon: 'user' },
    on_lead_deleted: { caption: 'Lead deleted', pill: { label: 'Deleted', tone: 'bad' }, byline: 'removed by {author}', icon: 'trash' },
    on_note_changed: { caption: 'Note updated', byline: '{author} edited the note', icon: 'edit' },
    on_note_created: { caption: 'New note', byline: 'added by {author}', icon: 'comment' },
    on_note_deleted: { caption: 'Note deleted', pill: { label: 'Deleted', tone: 'bad' }, byline: 'removed by {author}', icon: 'trash' },
    on_organization_changed: { caption: 'Organization updated', byline: '{author} updated the organization', icon: 'users' },
    on_organization_created: { caption: 'New organization', byline: 'added by {author}', icon: 'users' },
    on_organization_deleted: { caption: 'Organization deleted', pill: { label: 'Deleted', tone: 'bad' }, byline: 'removed by {author}', icon: 'trash' },
    on_person_changed: { caption: 'Person updated', byline: '{author} updated the person', icon: 'user' },
    on_person_created: { caption: 'New person', byline: 'added by {author}', icon: 'user' },
    on_person_deleted: { caption: 'Person deleted', pill: { label: 'Deleted', tone: 'bad' }, byline: 'removed by {author}', icon: 'trash' },
    on_pipedrive_any_event: { pill: { label: 'Event', tone: 'info' }, caption: 'Pipedrive update', byline: 'a record changed in your account', icon: 'refresh' },
    on_pipeline_changed: { caption: 'Pipeline updated', byline: '{author} updated the pipeline', icon: 'edit' },
    on_pipeline_created: { caption: 'New pipeline', byline: 'created by {author}', icon: 'file' },
    on_pipeline_deleted: { caption: 'Pipeline deleted', pill: { label: 'Deleted', tone: 'bad' }, byline: 'removed by {author}', icon: 'trash' },
    on_product_changed: { caption: 'Product updated', byline: '{author} updated the product', icon: 'edit' },
    on_product_created: { caption: 'New product', byline: 'added by {author}', icon: 'cart' },
    on_product_deleted: { caption: 'Product deleted', pill: { label: 'Deleted', tone: 'bad' }, byline: 'removed by {author}', icon: 'trash' },
    on_stage_changed: { caption: 'Stage updated', byline: '{author} updated the stage', icon: 'edit' },
    on_stage_created: { caption: 'New stage', byline: 'added by {author}', icon: 'file' },
    on_stage_deleted: { caption: 'Stage deleted', pill: { label: 'Deleted', tone: 'bad' }, byline: 'removed by {author}', icon: 'trash' },
    on_user_changed: { caption: 'User updated', byline: '{author} was updated', icon: 'user' },
    on_user_created: { caption: 'New user', byline: '{author} joined your company', icon: 'user' },
    on_user_deleted: { caption: 'User deleted', pill: { label: 'Deleted', tone: 'bad' }, byline: 'account removed', icon: 'trash' },
};

const SALESFORCE_OPS: Record<string, OpRender> = {
    on_approval_decision: { pill: { label: 'Approved', tone: 'good' }, caption: 'Approval decision', byline: '{author} responded to the approval request', icon: 'check' },
    on_chatter_mention: { caption: 'Chatter mention', byline: '{author} mentioned you', icon: 'comment' },
    on_new_account: { caption: 'New account', byline: 'created by {author}', icon: 'users' },
    on_new_approval_request: { pill: { label: 'Pending', tone: 'warn' }, caption: 'Approval request', byline: 'submitted by {author}', icon: 'shield' },
    on_new_case: { pill: { label: 'New', tone: 'brand' }, caption: 'New case', byline: 'opened by {author}', icon: 'card' },
    on_new_chatter_post_on_record: { caption: 'Chatter post', byline: '{author} posted on the record', icon: 'comment' },
    on_new_contact: { caption: 'New contact', byline: 'created by {author}', icon: 'user' },
    on_new_file_upload: { caption: 'New file', byline: '{author} uploaded a file', icon: 'file' },
    on_new_lead: { caption: 'New lead', pill: { label: 'Open', tone: 'brand' }, byline: 'created by {author}', icon: 'user' },
    on_new_opportunity: { caption: 'New opportunity', byline: 'created by {author}', icon: 'dollar' },
    on_new_task: { caption: 'New task', byline: 'assigned to {author}', icon: 'check' },
    on_new_user: { caption: 'New user', byline: '{author} was added to your org', icon: 'user' },
    on_opportunity_stage_change: { caption: 'Opportunity updated', pill: { label: 'Stage changed', tone: 'info' }, byline: '{author} moved the opportunity stage', icon: 'dollar' },
    on_report_threshold_crossed: { pill: { label: 'Threshold', tone: 'warn' }, caption: 'Report alert', byline: 'a report crossed its threshold', icon: 'alert' },
    on_updated_case: { caption: 'Case updated', pill: { label: 'Working', tone: 'info' }, byline: '{author} updated the case', icon: 'edit' },
    on_updated_lead: { caption: 'Lead updated', byline: '{author} updated the lead', icon: 'edit' },
    on_updated_opportunity: { caption: 'Opportunity updated', byline: '{author} updated the opportunity', icon: 'dollar' },
};

const NOTION_OPS: Record<string, OpRender> = {
    on_comment_created: { byline: '{author} commented', icon: 'comment' },
    on_database_created: { caption: 'New database', byline: 'created by {author}', icon: 'file' },
    on_database_item: { caption: 'New database item', byline: 'added by {author}', icon: 'card' },
    on_page_created: { caption: 'New page', byline: 'created by {author}', icon: 'file' },
    on_page_updated: { caption: 'Page edited', byline: '{author} edited the page', icon: 'edit' },
};

const MONDAY_OPS: Record<string, OpRender> = {
    on_board_event: { pill: { label: 'Event', tone: 'info' }, caption: 'Board update', byline: '{author} updated an item on the board', icon: 'card' },
};

const CLICKUP_OPS: Record<string, OpRender> = {
    on_task_event: { pill: { label: 'Event', tone: 'info' }, caption: 'Task update', byline: '{author} updated the task', icon: 'check' },
};

const TRELLO_OPS: Record<string, OpRender> = {
    on_board_change: { pill: { label: 'Event', tone: 'info' }, caption: 'Board activity', byline: '{author} updated the board', icon: 'file' },
    on_card_change: { pill: { label: 'Event', tone: 'info' }, caption: 'Card activity', byline: '{author} moved the card', icon: 'card' },
};

const ASANA_OPS: Record<string, OpRender> = {
    on_resource_change: { pill: { label: 'Event', tone: 'info' }, caption: 'Task update', byline: '{author} changed a task', icon: 'check' },
};

const WEBFLOW_OPS: Record<string, OpRender> = {
    collection_item_changed: { caption: 'Item updated', byline: '{author} updated the collection item', icon: 'edit' },
    collection_item_created: { caption: 'New item', byline: 'added to the collection by {author}', icon: 'file' },
    collection_item_deleted: { caption: 'Item deleted', pill: { label: 'Deleted', tone: 'bad' }, byline: 'removed by {author}', icon: 'trash' },
    collection_item_published: { caption: 'Item published', pill: { label: 'Published', tone: 'good' }, byline: 'published live by {author}', icon: 'check' },
    collection_item_unpublished: { caption: 'Item unpublished', pill: { label: 'Unpublished', tone: 'neutral' }, byline: 'taken off the live site by {author}', icon: 'eye' },
    comment_created: { byline: '{author} left a comment', icon: 'comment' },
    ecomm_inventory_changed: { caption: 'Inventory updated', byline: 'stock level changed', icon: 'cart' },
    ecomm_new_order: { caption: 'New order', pill: { label: 'Unfulfilled', tone: 'warn' }, byline: 'placed by {author}', icon: 'cart' },
    ecomm_order_changed: { caption: 'Order updated', byline: '{author} updated the order', icon: 'cart' },
    form_submission: { caption: 'New response', byline: 'submitted by {author}', icon: 'form' },
    page_created: { caption: 'New page', byline: 'created by {author}', icon: 'file' },
    page_deleted: { caption: 'Page deleted', pill: { label: 'Deleted', tone: 'bad' }, byline: 'removed by {author}', icon: 'trash' },
    page_metadata_updated: { caption: 'Page settings updated', byline: '{author} changed the page metadata', icon: 'edit' },
    site_publish: { caption: 'Site published', pill: { label: 'Published', tone: 'good' }, byline: '{author} published the site', icon: 'check' },
};

const GOOGLE_DRIVE_OPS: Record<string, OpRender> = {
    on_drive_change: { pill: { label: 'Event', tone: 'info' }, caption: 'Drive update', byline: 'something changed in this Drive', icon: 'file' },
    on_file_changed: { caption: 'File updated', byline: '{author} made changes to the file', icon: 'edit' },
    on_file_removed: { caption: 'File removed', pill: { label: 'Trashed', tone: 'bad' }, byline: '{author} moved the file to Trash', icon: 'trash' },
    on_folder_changed: { caption: 'Folder updated', byline: '{author} changed the folder', icon: 'file' },
    on_folder_removed: { caption: 'Folder removed', pill: { label: 'Trashed', tone: 'bad' }, byline: '{author} moved the folder to Trash', icon: 'trash' },
};

const GOOGLE_SHEETS_OPS: Record<string, OpRender> = {
    on_new_row: { caption: 'New row', byline: 'added to the sheet by {author}', icon: 'file' },
};

const TYPEFORM_OPS: Record<string, OpRender> = {
    on_new_form_response: { caption: 'New response', pill: { label: 'Completed', tone: 'good' }, byline: 'submitted by {author}', icon: 'form' },
};

const GOOGLE_FORMS_OPS: Record<string, OpRender> = {
    on_form_response: { caption: 'New response', byline: 'submitted by {author}', icon: 'form' },
};

// Chat apps — entries are SYSTEM LINES above the message; a plain incoming
// message needs no entry.
const SLACK_OPS: Record<string, OpRender> = {
    on_app_mention: { byline: '{author} mentioned the app', icon: 'bell' },
    on_channel_created: { byline: '{author} created the channel', icon: 'comment' },
    on_file_shared: { byline: '{author} shared a file', icon: 'file' },
    on_member_joined_channel: { byline: '{author} joined the channel', icon: 'user' },
    on_reaction_added: { byline: '{author} reacted to a message', icon: 'star' },
};

const DISCORD_OPS: Record<string, OpRender> = {
    on_application_authorized: { pill: { label: 'Added', tone: 'good' }, byline: '{author} added the app to the server', icon: 'shield' },
    on_application_deauthorized: { pill: { label: 'Removed', tone: 'bad' }, byline: '{author} removed the app', icon: 'shield' },
    on_entitlement_create: { pill: { label: 'Active', tone: 'good' }, byline: '{author} started a subscription', icon: 'dollar' },
    on_entitlement_delete: { pill: { label: 'Revoked', tone: 'bad' }, byline: "{author}'s subscription was revoked", icon: 'trash' },
    on_entitlement_update: { pill: { label: 'Renewed', tone: 'info' }, byline: "{author}'s subscription was updated", icon: 'refresh' },
    on_slash_command: { byline: '{author} used a slash command', icon: 'comment' },
    // on_message is a plain incoming message and deliberately has no entry.
    on_mention: { byline: '{author} mentioned the bot', icon: 'bell' },
};

const MICROSOFT_TEAMS_OPS: Record<string, OpRender> = {
    on_change_notification: { pill: { label: 'Event', tone: 'info' }, byline: 'a subscribed resource changed', icon: 'bell' },
};

const FACEBOOK_OPS: Record<string, OpRender> = {
    on_any_facebook_event: { pill: { label: 'Event', tone: 'info' }, byline: 'a new update from your Page', icon: 'bell' },
    on_feed: { byline: '{author} posted to your Page', icon: 'edit' },
    on_mention: { byline: '{author} mentioned your Page', icon: 'bell' },
    on_message_deliveries: { pill: { label: 'Delivered', tone: 'neutral' }, byline: 'message delivered to {author}', icon: 'check' },
    on_message_reactions: { byline: '{author} reacted to a message', icon: 'star' },
    on_message_reads: { pill: { label: 'Seen', tone: 'neutral' }, byline: '{author} read your message', icon: 'eye' },
    on_messaging_postbacks: { byline: '{author} tapped a button', icon: 'card' },
    on_messaging_referrals: { byline: '{author} started a chat from a link', icon: 'user' },
    on_ratings: { pill: { label: 'Recommends', tone: 'good' }, byline: '{author} left a recommendation', icon: 'star' },
    on_standby: { pill: { label: 'Standby', tone: 'neutral' }, byline: 'another app is handling this conversation', icon: 'eye' },
};

const WHATSAPP_OPS: Record<string, OpRender> = {
    receive_status_update: { pill: { label: 'Delivered', tone: 'neutral' }, byline: 'message status updated for {author}', icon: 'check' },
};

export const APP_OP_RENDERS: Record<string, Record<string, OpRender>> = {
    github: GITHUB_OPS,
    gitlab: GITLAB_OPS,
    linear: LINEAR_OPS,
    jira: JIRA_OPS,
    sentry: SENTRY_OPS,
    datadog: DATADOG_OPS,
    pagerduty: PAGERDUTY_OPS,
    firestore: FIRESTORE_OPS,
    stripe: STRIPE_OPS,
    shopify: SHOPIFY_OPS,
    zoom: ZOOM_OPS,
    calendly: CALENDLY_OPS,
    cal_com: CAL_COM_OPS,
    google_calendar: GOOGLE_CALENDAR_OPS,
    mailgun: MAILGUN_OPS,
    zendesk: ZENDESK_OPS,
    intercom: INTERCOM_OPS,
    hubspot: HUBSPOT_OPS,
    pipedrive: PIPEDRIVE_OPS,
    salesforce: SALESFORCE_OPS,
    notion: NOTION_OPS,
    monday: MONDAY_OPS,
    clickup: CLICKUP_OPS,
    trello: TRELLO_OPS,
    asana: ASANA_OPS,
    webflow: WEBFLOW_OPS,
    google_drive: GOOGLE_DRIVE_OPS,
    google_sheets: GOOGLE_SHEETS_OPS,
    typeform: TYPEFORM_OPS,
    google_forms: GOOGLE_FORMS_OPS,
    slack: SLACK_OPS,
    discord: DISCORD_OPS,
    microsoft_teams: MICROSOFT_TEAMS_OPS,
    facebook: FACEBOOK_OPS,
    whatsapp: WHATSAPP_OPS,
};

/** Generic action lexicon — the fallback for operations no table names.
    Matches the ACTION tail of the op so `on_widget_unpinned` still reads
    "unpinned" with a pin glyph. Order matters: negations before their base
    ('unassigned' before 'assigned'), specific before broad. */
const GENERIC_ACTIONS: Array<[RegExp, OpRender]> = [
    [/unassign/, { byline: 'unassigned by {author}', icon: 'user' }],
    [/assign/, { byline: 'assigned by {author}', icon: 'user' }],
    [/unlabel/, { byline: 'label removed by {author}', icon: 'label' }],
    [/label/, { byline: 'labeled by {author}', icon: 'label' }],
    [/unpin/, { byline: 'unpinned by {author}', icon: 'pin' }],
    [/pin/, { byline: 'pinned by {author}', icon: 'pin' }],
    [/unlock/, { byline: 'unlocked by {author}', icon: 'lock' }],
    [/lock/, { pill: { label: 'Locked', tone: 'warn' }, byline: 'locked by {author}', icon: 'lock' }],
    [/demileston/, { byline: 'removed from milestone by {author}', icon: 'milestone' }],
    [/mileston/, { byline: 'added to milestone by {author}', icon: 'milestone' }],
    [/transfer/, { byline: 'transferred by {author}' }],
    [/archiv/, { pill: { label: 'Archived', tone: 'neutral' }, byline: 'archived by {author}' }],
    [/unpublish/, { pill: { label: 'Unpublished', tone: 'neutral' }, byline: 'unpublished by {author}' }],
    [/publish/, { pill: { label: 'Published', tone: 'good' }, byline: 'published by {author}' }],
    [/delet|remov|trash/, { pill: { label: 'Deleted', tone: 'bad' }, byline: 'deleted by {author}', icon: 'trash' }],
    [/cancel/, { pill: { label: 'Cancelled', tone: 'bad' }, byline: 'cancelled by {author}' }],
    [/reopen/, { pill: { label: 'Reopened', tone: 'good' }, byline: 'reopened by {author}' }],
    [/clos/, { pill: { label: 'Closed', tone: 'bad' }, byline: 'closed by {author}' }],
    [/merg/, { pill: { label: 'Merged', tone: 'info' }, byline: 'merged by {author}', icon: 'merge' }],
    [/resolve|recover/, { pill: { label: 'Resolved', tone: 'good' }, byline: 'resolved by {author}', icon: 'check' }],
    [/complet|done|fulfill?ed|succeed/, { pill: { label: 'Completed', tone: 'good' }, byline: 'completed', icon: 'check' }],
    [/fail/, { pill: { label: 'Failed', tone: 'bad' }, icon: 'alert' }],
    [/expir/, { pill: { label: 'Expired', tone: 'warn' } }],
    [/pause/, { pill: { label: 'Paused', tone: 'warn' } }],
    [/resum/, { pill: { label: 'Resumed', tone: 'good' } }],
    [/renam/, { byline: 'renamed by {author}', icon: 'edit' }],
    [/edit|updat|chang|modif/, { byline: 'updated by {author}', icon: 'edit' }],
    [/comment|repl/, { byline: '{author} commented', icon: 'comment' }],
    [/mention/, { byline: '{author} mentioned you' }],
    [/react/, { byline: '{author} reacted' }],
    [/join/, { byline: '{author} joined', icon: 'user' }],
    [/left|leave/, { byline: '{author} left', icon: 'user' }],
    [/invit/, { byline: '{author} invited', icon: 'user' }],
    [/mov/, { byline: 'moved by {author}' }],
    [/duplicat|copy/, { byline: 'duplicated by {author}' }],
    [/creat|open|new_|added|add_/, { byline: 'created by {author}' }],
];

/** Table hit → generic lexicon → undefined (the shape keeps its defaults). */
export function resolveOpRender(
    slug: string | undefined,
    operation: string | undefined
): OpRender | undefined {
    if (!operation) return undefined;
    const table = slug ? APP_OP_RENDERS[slug] : undefined;
    const hit = table?.[operation];
    if (hit) return hit;
    const s = operation.toLowerCase();
    for (const [re, render] of GENERIC_ACTIONS) {
        if (re.test(s)) return render;
    }
    return undefined;
}

/** Replace the {author} placeholder with the staged sender. */
export function conjugate(byline: string, author?: string): string {
    return byline.replace('{author}', author ?? 'someone');
}
