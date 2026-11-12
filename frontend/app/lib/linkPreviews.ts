// What a link to a NoClick page shows where it's sent (WhatsApp, iMessage, Slack, X): a title, one line and a picture
// saying what the link is for. Each picture is drawn once, per kind of link and per account a connect link asks for,
// and served from /previews/<version>/. Crawlers fetch and cache previews, so a preview names nothing a stranger
// holding the link shouldn't learn: never a token, an email, a person's name or an amount. This module imports
// nothing: the landing page and every page's head read it.

/** Every picture's folder. A changed picture needs a new address, since previews are cached by it. */
export const PREVIEWS_VERSION = 'v1';

/** A drawn glyph, for a link whose subject isn't an app. */
export type PreviewGlyph =
    | 'plug'
    | 'check'
    | 'question'
    | 'request'
    | 'chat'
    | 'play'
    | 'wallet'
    | 'upgrade'
    | 'invite'
    | 'space'
    | 'lock'
    | 'key'
    | 'pen'
    | 'browser'
    | 'card'
    | 'rupee'
    | 'sign-in';

/** One disc at the top of a picture: an account's mark (by a credential type of its), a glyph, or a texting app. */
export type PreviewMark = { account: string } | { glyph: PreviewGlyph } | { channel: 'whatsapp' | 'imessage' };

/** A picture: its discs, then its headline in the landing's two tones (a statement, then an italic line carrying on). */
export interface PreviewArt {
    key: string;
    marks: PreviewMark[];
    title: string;
    more?: string;
    /** NoClick's mark under the headline; off on a page another brand serves. */
    signed?: boolean;
}

export interface LinkPreview {
    title: string;
    description: string;
    /** The picture's path, which `buildSeoMeta` makes absolute on the site's origin. */
    image: string;
}

export function previewImage(key: string): string {
    return `/previews/${PREVIEWS_VERSION}/${key}.jpg`;
}

const slug = (name: string) => name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');

/** The accounts connect links ask for most, each with a picture of its own, by the name a preview gives it and a
 *  credential type of it. Any other account gets the plain connect picture, its name still in the title. */
export const CONNECT_ACCOUNTS: Readonly<Record<string, string>> = {
    Claude: 'agent_claude_code_oauth',
    Anthropic: 'agent_anthropic',
    ChatGPT: 'agent_codex_oauth',
    OpenAI: 'agent_openai',
    'Google Gemini': 'agent_gemini',
    OpenRouter: 'agent_openrouter',
    OpenCode: 'agent_opencode',
    xAI: 'agent_xai_oauth',
    Groq: 'agent_groq',
    DeepSeek: 'agent_deepseek',
    'Mistral AI': 'agent_mistral',
    NVIDIA: 'agent_nvidia',
    'GitHub Copilot': 'agent_github_copilot',
    GitHub: 'github_oauth',
    Gmail: 'google_gmail_oauth',
    Slack: 'slack_oauth',
    WhatsApp: 'whatsapp_qr',
    'Google Calendar': 'google_calendar_oauth',
    'Google Sheets': 'google_sheets_oauth',
    'Google Drive': 'google_drive_oauth',
    Notion: 'notion_oauth',
    Outlook: 'microsoft_outlook_oauth',
    Linear: 'linear_oauth',
    HubSpot: 'hubspot_oauth',
    Airtable: 'airtable_oauth',
};

const CONNECT_ANY: PreviewArt = { key: 'connect', marks: [{ glyph: 'plug' }], title: 'Connect', more: 'an account' };

const connectArt = (name: string): PreviewArt => ({
    key: `connect-${slug(name)}`,
    marks: [{ account: CONNECT_ACCOUNTS[name] }],
    title: 'Connect your',
    more: `${name} account`,
});

/** The picture for connecting an account by its name: its own when it has one, else the plain one. */
export function connectImage(name: string | null): string {
    return previewImage(name && name in CONNECT_ACCOUNTS ? connectArt(name).key : CONNECT_ANY.key);
}

const CONNECT_LINE = 'Open the link to connect it for their NoClick automations. You don’t need a NoClick account.';

/** A connect link's preview: the account it asks for when the request could be read, else any account. */
export function connectPreview(name: string | null): LinkPreview {
    return { title: name ? `Connect your ${name} account` : 'Connect an account', description: CONNECT_LINE, image: connectImage(name) };
}

/** Every picture the shipped pages use, for the lab that draws them. */
export const SHARED_ARTS: readonly PreviewArt[] = [CONNECT_ANY, ...Object.keys(CONNECT_ACCOUNTS).map(connectArt)];
