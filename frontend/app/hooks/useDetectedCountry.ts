// The visitor's likely country, for preselecting a phone input's calling code:
// the IP country /api/public-session reports (Vercel geolocation), else the
// browser locale's region, else nothing (the input then starts international).
import { isSupportedCountry, type CountryCode } from 'libphonenumber-js';
import { usePublicSession } from '~/hooks/usePublicSession';

function localeCountry(): string | undefined {
    if (typeof navigator === 'undefined') return undefined;
    for (const tag of navigator.languages ?? [navigator.language]) {
        const region = tag.split('-')[1];
        if (region && region.length === 2) return region.toUpperCase();
    }
    return undefined;
}

export function useDetectedCountry(): CountryCode | undefined {
    const { country } = usePublicSession();
    const guess = country?.toUpperCase() || localeCountry();
    return guess && isSupportedCountry(guess) ? guess : undefined;
}
