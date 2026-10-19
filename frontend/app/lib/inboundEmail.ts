import { isLocalEdition } from '~/lib/edition';

// NoClick's own mail domains: a community build may never display or mint on them.
const NOCLICK_MAIL_DOMAINS = new Set(['noclick.app', 'noclick.email']);

/** Mail domain this build mints and displays new addresses on.
 *
 * Hosted keeps its owned default (an address minted on noclick.app before it
 * moved still reaches its inbox at noclick.email). Community builds require an
 * operator-owned domain at build time and return null otherwise, so they can
 * never display or mint an address on NoClick's mail system.
 */
export function inboundEmailDomain(): string | null {
    const configured =
        import.meta.env.VITE_INBOUND_EMAIL_DOMAIN?.trim().toLowerCase();
    if (configured) {
        if (!/^[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$/.test(configured)) return null;
        if (isLocalEdition() && NOCLICK_MAIL_DOMAINS.has(configured))
            return null;
        return configured;
    }
    return isLocalEdition() ? null : 'noclick.email';
}
