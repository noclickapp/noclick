// A country's name in English from its ISO code (the code itself where the browser can't name it). Apart from the
// country picker so the many places that name a country don't load every flag.
const regionNames = typeof Intl !== 'undefined' && 'DisplayNames' in Intl ? new Intl.DisplayNames(['en'], { type: 'region' }) : null;

export function countryName(code: string): string {
    return regionNames?.of(code) ?? code;
}
