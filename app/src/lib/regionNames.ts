// What each NoClick region is called on a page, and where it is (the API's /v1/regions labels and locations, written
// once for the pages that show a region without reading them): the price list and Work's machine picker.
export const REGION_NAMES: Record<string, string> = { eu: 'Europe', 'us-east': 'US East', 'us-west': 'US West', ap: 'Asia Pacific', in: 'India' };
export const REGION_PLACES: Record<string, string> = {
    eu: 'The European Economic Area',
    'us-east': 'The eastern United States',
    'us-west': 'The western United States',
    ap: 'Asia and the Pacific',
    in: 'India',
};
