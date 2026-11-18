// A guess at the country someone is in, from their browser's languages: the region of the first one that names one
// (`en-GB` is GB). For opening a country's choice on a likely one; never proof of where anyone is.
import { useEffect, useState } from 'react';

export function localeCountry(): string | undefined {
    if (typeof navigator === 'undefined') return undefined;
    for (const tag of navigator.languages ?? [navigator.language]) {
        const region = tag.split('-')[1];
        if (region && region.length === 2) return region.toUpperCase();
    }
    return undefined;
}

/** `localeCountry()` once the page is in a browser: undefined while it renders on a server, so both render alike. */
export function useLocaleCountry(): string | undefined {
    const [country, setCountry] = useState<string>();
    useEffect(() => setCountry(localeCountry()), []);
    return country;
}
