import type { PublicOAuthProvider } from '~/utils/integrationMetadata';

/** Public, non-secret context only. The backend repeats all validation before I/O. */
export function validateOAuthContext(
    spec: PublicOAuthProvider,
    context: Record<string, string>,
    sources: string[]
): Record<string, string> {
    const fields = spec.contextFields ?? {};
    const allowed = Object.entries(fields).filter(([, field]) =>
        sources.includes(field.source)
    );
    if (
        Object.keys(context).some(
            (key) => !allowed.some(([name]) => key === name)
        )
    )
        throw new Error('Unknown OAuth context field');
    return Object.fromEntries(
        allowed.map(([name, field]) => {
            const value = context[name];
            if (
                typeof value !== 'string' ||
                !value ||
                value.length > 2048 ||
                (field.choices.length && !field.choices.includes(value)) ||
                (field.pattern &&
                    !new RegExp(`^(?:${field.pattern})$`).test(value))
            )
                throw new Error(`Invalid ${field.label || name}`);
            if (field.kind === 'host' || field.kind === 'origin') {
                const url = new URL(
                    field.kind === 'host' ? `https://${value}` : value
                );
                if (
                    url.protocol !== 'https:' ||
                    url.username ||
                    url.password ||
                    url.port ||
                    url.pathname !== '/' ||
                    url.search ||
                    url.hash ||
                    url.hostname.length > 253 ||
                    !url.hostname
                        .split('.')
                        .every((label) =>
                            /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/.test(label)
                        ) ||
                    (field.kind === 'host'
                        ? url.hostname !== value
                        : url.origin !== value)
                )
                    throw new Error(`Invalid ${field.label || name}`);
            }
            return [name, value];
        })
    );
}

export function oauthEndpoint(
    template: string,
    spec: PublicOAuthProvider,
    context: Record<string, string>
) {
    return template.replace(/\{([a-z][a-z0-9_]*)\}/g, (_, key: string) => {
        if (
            !Object.hasOwn(context, key) ||
            !Object.hasOwn(spec.contextFields ?? {}, key)
        )
            throw new Error('Missing OAuth URL context');
        return spec.contextFields![key].kind === 'value'
            ? encodeURIComponent(context[key]).replace(
                  /[!'()*]/g,
                  (char) => `%${char.charCodeAt(0).toString(16).toUpperCase()}`
              )
            : context[key];
    });
}
