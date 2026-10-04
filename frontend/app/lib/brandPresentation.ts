// An account's brand as a public page may render it (a person's request page,
// a shared agent's chat page): only https URLs and a #rrggbb accent get through.

export interface Brand {
    name: string;
    logo_url: string | null;
    color: string | null;
    support_url: string | null;
}

const HEX_RE = /^#[0-9a-f]{6}$/i;

export function httpsUrl(value: string | null): string | null {
    if (!value) return null;
    try {
        return new URL(value).protocol === 'https:' ? value : null;
    } catch {
        return null;
    }
}

export function brandPresentation(brand: Brand) {
    return {
        name: brand.name,
        logoUrl: httpsUrl(brand.logo_url),
        accent: brand.color && HEX_RE.test(brand.color) ? brand.color : null,
        supportUrl: httpsUrl(brand.support_url),
    };
}
