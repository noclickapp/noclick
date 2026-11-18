// An app's own domains, as the developer console's app drawer and the app's page in Resources show and change
// them: the names its domains serve it at (a domain's www goes with its own name), serving it at another name, and
// stopping. A write makes every read showing it stale (the app's domains and URL, the domains' lists) under the
// surface's key prefix: '' in the console, 'resources:' in Resources.
import { useState } from 'react';
import { invalidateV1 } from '@/sdk/useV1';
import type { Domain, Project } from 'noclick';

export type ReadPrefix = '' | 'resources:';

/** A typed name as a domain: lowercase, without a scheme, a path or a trailing dot. */
export function domainName(text: string): string {
    return text
        .trim()
        .toLowerCase()
        .replace(/^[a-z]+:\/\//, '')
        .replace(/\/.*$/, '')
        .replace(/\.$/, '');
}

/** A name a domain can serve at: `bakery.com`, `shop.bakery.com`. */
export function isDomainName(name: string): boolean {
    return /^([a-z0-9-]+\.)+[a-z]{2,}$/.test(name);
}

/** One name an app is served at, and every name removing it stops: a domain's own name takes its www with it. */
export interface ServedName {
    domain: Domain;
    hostname: string;
    stops: string[];
}

/** The names `domains` serve the app `projectId` at, one each: www isn't one of its own beside its domain's name. */
export function servedNames(domains: readonly Domain[], projectId: string): ServedName[] {
    return domains.flatMap((domain) => {
        const served = domain.serves.filter((s) => s.kind === 'project' && s.id === projectId).map((s) => s.hostname);
        return served
            .filter((h) => !(h === `www.${domain.name}` && served.includes(domain.name)))
            .map((hostname) => ({ domain, hostname, stops: hostname === domain.name ? served.filter((h) => h === hostname || h === `www.${hostname}`) : [hostname] }));
    });
}

function moved(prefix: ReadPrefix): void {
    invalidateV1(`${prefix}projects`);
    invalidateV1(`${prefix}domains`);
}

/** Serve the app at `name` too: a domain the account holds, or a name under one, at once; any other is connected first. */
export async function serveAppAt(project: Project, name: string, prefix: ReadPrefix): Promise<Domain> {
    const domain = await project.addDomain(name);
    moved(prefix);
    return domain;
}

/** Stop serving the app at `served` (and its www, for a domain's own name); the domain stays. */
export async function stopServing(project: Project, served: ServedName, prefix: ReadPrefix): Promise<void> {
    await project.removeDomain(served.hostname);
    moved(prefix);
}

/** A dialog's add: the domain it answered, or why it couldn't. */
export function useAddAppDomain(project: Project, prefix: ReadPrefix) {
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<unknown>(undefined);
    const [added, setAdded] = useState<Domain | null>(null);
    const add = async (name: string): Promise<Domain | null> => {
        setBusy(true);
        setError(undefined);
        try {
            const domain = await serveAppAt(project, name, prefix);
            setAdded(domain);
            return domain;
        } catch (e) {
            setError(e);
            return null;
        } finally {
            setBusy(false);
        }
    };
    const reset = () => {
        setAdded(null);
        setError(undefined);
    };
    return { busy, error, added, add, reset };
}
