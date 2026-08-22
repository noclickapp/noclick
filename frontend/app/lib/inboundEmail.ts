import { isLocalEdition } from '~/lib/edition';

/** Mail domain this build may display or reserve.
 *
 * Hosted keeps its owned default. Community builds require an operator-owned
 * domain at build time and return null otherwise, so they can never display or
 * mint an address on NoClick's mail system.
 */
export function inboundEmailDomain(): string | null {
    const configured =
        import.meta.env.VITE_INBOUND_EMAIL_DOMAIN?.trim().toLowerCase();
    if (configured) {
        if (!/^[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$/.test(configured)) return null;
        if (isLocalEdition() && configured === 'noclick.app') return null;
        return configured;
    }
    return isLocalEdition() ? null : 'noclick.app';
}
