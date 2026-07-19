// Human-readable credential naming, one place. Backend method labels are raw
// Pydantic class names ("WhatsAppAccessToken", "NotionOAuth") and
// credential_type slugs title-case badly ("whatsapp_qr" → "Whatsapp Qr");
// these helpers fix both generically: camel-splitting with acronym-run
// preservation, then restoring compound brand names the split necessarily
// breaks ("WhatsApp" → "Whats App") — the restore forms are DERIVED from the
// brand list by applying the same splitter, so the two can't drift.

// Casings plain Title Case gets wrong — single-token acronyms and brands
// (used on the snake_case path, where tokens arrive whole).
const WORD_CASING: Record<string, string> = {
  qr: 'QR', api: 'API', oauth: 'OAuth', pat: 'PAT', id: 'ID', url: 'URL',
  sso: 'SSO', ai: 'AI', whatsapp: 'WhatsApp', github: 'GitHub',
  gitlab: 'GitLab', hubspot: 'HubSpot', linkedin: 'LinkedIn',
  paypal: 'PayPal', tiktok: 'TikTok', youtube: 'YouTube', posthog: 'PostHog',
  openai: 'OpenAI', clickup: 'ClickUp', pagerduty: 'PagerDuty',
  bamboohr: 'BambooHR', quickbooks: 'QuickBooks',
};

// Compound names the camel-splitter necessarily breaks apart.
const COMPOUND_BRANDS = [
  'WhatsApp', 'GitHub', 'GitLab', 'HubSpot', 'LinkedIn', 'PayPal', 'TikTok',
  'YouTube', 'PostHog', 'OpenAI', 'ClickUp', 'PagerDuty', 'BambooHR',
  'QuickBooks', 'OAuth',
];

function camelSplit(text: string): string {
  return text
    // lower/digit → Upper boundary: "AccessToken" → "Access Token"
    .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
    // acronym-run → Word boundary: "QRCode" → "QR Code" (keeps "QR" intact)
    .replace(/([A-Z]+)([A-Z][a-z])/g, '$1 $2');
}

export function fixWordCasing(text: string): string {
  return text
    .split(' ')
    .map(w => WORD_CASING[w.toLowerCase()] ?? w)
    .join(' ');
}

/** "WhatsAppAccessToken" → "WhatsApp Access Token"; "NotionOAuth" →
 *  "Notion OAuth"; "WhatsAppQR" → "WhatsApp QR". Already-spaced labels pass
 *  through with only casing fixes. */
export function humanizeCredentialLabel(label: string): string {
  let out = camelSplit(label);
  for (const brand of COMPOUND_BRANDS) {
    const splitForm = camelSplit(brand);
    if (splitForm !== brand) out = out.split(splitForm).join(brand);
  }
  return fixWordCasing(out);
}
