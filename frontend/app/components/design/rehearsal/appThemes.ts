/* Per-app visual identity for the rehearsal's native frames: the staged
   trigger and the outcome render in the COLORS and SHAPE of the app they
   represent — WhatsApp's green bubble on its dark chat, a GitHub issue card,
   a Monday item row, a Stripe payment — so non-technical users recognise
   their own tools at a glance. Deliberate brand islands (fixed hex, identical
   in both product themes), the same stance as the marketing hero bands.

   `shape` picks the bespoke composition (bespokeFrames.tsx); the palette
   fills it in. Sibling apps share a composition only when their real
   artifact genuinely looks alike (Typeform/Google Forms responses); iconic
   apps get their own. Keyed by the backend tool-name slug
   (`automation-cal-com` → `cal_com`) with aliases for API-suffixed types.
   An app without an entry falls back to the neutral structural frames —
   never a wrong brand. */

export type AppShape =
    | 'bubble'      // WhatsApp / Telegram / iMessage chat
    | 'row'         // Slack / Discord / Teams message row
    | 'email'       // Gmail / Outlook reading pane
    | 'github'      // issue card with state pill
    | 'gitlab'
    | 'linear'      // identifier + priority issue row
    | 'jira'
    | 'notion'      // page with title + content
    | 'monday'      // board item with status pill
    | 'clickup'
    | 'trello'      // card on a list
    | 'asana'       // task row with round check
    | 'todoist'
    | 'stripe'      // payment event with amount-ish badge
    | 'shopify'     // order card
    | 'booking'     // Cal.com / Calendly / Zoom / GCal date-block invite
    | 'response'    // Typeform / Google Forms / site form answer
    | 'sheet'       // Sheets / Airtable new-row grid
    | 'record'      // HubSpot / Pipedrive / Salesforce CRM record
    | 'ticket'      // Zendesk / Intercom conversation
    | 'alert'       // Datadog / Sentry / PagerDuty monitor
    | 'post'        // Reddit / X / Facebook / Instagram / YouTube
    | 'file'        // Dropbox / Drive file event
    | 'event';      // themed fallback card

export interface AppTheme {
    /** Human name, for badges inside the bespoke shapes ("Open", app-specific
        captions) and a11y. The card header already names the app. */
    name: string;
    shape: AppShape;
    /** The app's own surface. Light surfaces are intentional — Gmail IS white. */
    surface: string;
    /** "Their message" container (bubble/row hover). */
    bubbleIn?: string;
    /** The app's iconic "your message" color (outbound bubble). */
    bubbleOut?: string;
    /** Author/name ink. */
    author: string;
    /** Brand accent — mentions, links, pills, the shape's signature hue. */
    accent: string;
    /** Primary text ink on the surface. */
    ink: string;
    /** Secondary ink — timestamps, handles, captions. */
    sub: string;
    /** Hairlines inside the frame. */
    border: string;
    /** Stamped from the map key — bespoke frames key sub-variants on it. */
    slug?: string;
}

const APP_THEME_DEFS: Record<string, Omit<AppTheme, 'slug'>> = {
    /* ------------------------------------------------ chat bubbles */
    whatsapp: {
        name: 'WhatsApp', shape: 'bubble',
        surface: '#0b141a', bubbleIn: '#202c33', bubbleOut: '#005c4b',
        author: '#25d366', accent: '#53bdeb', ink: '#e9edef', sub: '#8696a0',
        border: 'rgba(233,237,239,0.08)',
    },
    telegram: {
        name: 'Telegram', shape: 'bubble',
        surface: '#0e1621', bubbleIn: '#182533', bubbleOut: '#2b5278',
        author: '#64b5ef', accent: '#64b5ef', ink: '#f5f5f5', sub: '#708499',
        border: 'rgba(245,245,245,0.08)',
    },
    twilio: {
        name: 'Messages', shape: 'bubble',
        surface: '#000000', bubbleIn: '#26252a', bubbleOut: '#0a84ff',
        author: '#8e8e93', accent: '#0a84ff', ink: '#ffffff', sub: '#8e8e93',
        border: 'rgba(255,255,255,0.08)',
    },

    /* ------------------------------------------------ chat rows */
    slack: {
        name: 'Slack', shape: 'row',
        surface: '#1a1d21', bubbleIn: 'rgba(255,255,255,0.04)',
        author: '#d1d2d3', accent: '#1d9bd1', ink: '#d1d2d3', sub: '#9a9b9e',
        border: 'rgba(209,210,211,0.08)',
    },
    discord: {
        name: 'Discord', shape: 'row',
        surface: '#313338', bubbleIn: 'rgba(255,255,255,0.03)',
        author: '#949cf7', accent: '#5865f2', ink: '#dbdee1', sub: '#949ba4',
        border: 'rgba(219,222,225,0.08)',
    },
    microsoft_teams: {
        name: 'Teams', shape: 'row',
        surface: '#292929', bubbleIn: 'rgba(255,255,255,0.04)',
        author: '#ffffff', accent: '#7f85f5', ink: '#ffffff', sub: '#adadad',
        border: 'rgba(255,255,255,0.08)',
    },

    /* ------------------------------------------------ email panes */
    gmail: {
        name: 'Gmail', shape: 'email',
        surface: '#ffffff', author: '#202124', accent: '#ea4335',
        ink: '#202124', sub: '#5f6368', border: '#e8eaed',
    },
    outlook: {
        name: 'Outlook', shape: 'email',
        surface: '#ffffff', author: '#242424', accent: '#0f6cbd',
        ink: '#242424', sub: '#616161', border: '#e6e6e6',
    },
    mailgun: {
        name: 'Mailgun', shape: 'email',
        surface: '#ffffff', author: '#20232a', accent: '#c02428',
        ink: '#20232a', sub: '#6b7280', border: '#e5e7eb',
    },
    mailchimp: {
        name: 'Mailchimp', shape: 'email',
        surface: '#ffffff', author: '#241c15', accent: '#007c89',
        ink: '#241c15', sub: '#736c64', border: '#e7e5e4',
    },
    sendgrid: {
        name: 'SendGrid', shape: 'email',
        surface: '#ffffff', author: '#1c1c1e', accent: '#1a82e2',
        ink: '#1c1c1e', sub: '#6b7280', border: '#e5e7eb',
    },
    send_email: {
        name: 'Email', shape: 'email',
        surface: '#ffffff', author: '#18181b', accent: '#18181b',
        ink: '#18181b', sub: '#71717a', border: '#e4e4e7',
    },

    /* ------------------------------------------------ dev trackers */
    github: {
        name: 'GitHub', shape: 'github',
        surface: '#0d1117', author: '#e6edf3', accent: '#3fb950',
        ink: '#e6edf3', sub: '#7d8590', border: '#30363d',
    },
    gitlab: {
        name: 'GitLab', shape: 'gitlab',
        surface: '#ffffff', author: '#333238', accent: '#fc6d26',
        ink: '#333238', sub: '#737278', border: '#dcdcde',
    },
    linear: {
        name: 'Linear', shape: 'linear',
        surface: '#191a23', author: '#f7f8f8', accent: '#5e6ad2',
        ink: '#f7f8f8', sub: '#8a8f98', border: 'rgba(247,248,248,0.1)',
    },
    jira: {
        name: 'Jira', shape: 'jira',
        surface: '#ffffff', author: '#172b4d', accent: '#0052cc',
        ink: '#172b4d', sub: '#6b778c', border: '#dfe1e6',
    },
    sentry: {
        name: 'Sentry', shape: 'alert',
        surface: '#362d59', author: '#f6f6f8', accent: '#e1567c',
        ink: '#f6f6f8', sub: '#a99fce', border: 'rgba(246,246,248,0.14)',
    },
    datadog: {
        name: 'Datadog', shape: 'alert',
        surface: '#ffffff', author: '#33344a', accent: '#632ca6',
        ink: '#33344a', sub: '#6f7086', border: '#e4e4ea',
    },
    pagerduty: {
        name: 'PagerDuty', shape: 'alert',
        surface: '#ffffff', author: '#232323', accent: '#06ac38',
        ink: '#232323', sub: '#767676', border: '#e5e5e5',
    },
    supabase: {
        name: 'Supabase', shape: 'event',
        surface: '#1c1c1c', author: '#ededed', accent: '#3ecf8e',
        ink: '#ededed', sub: '#898989', border: 'rgba(237,237,237,0.12)',
    },
    firestore: {
        name: 'Firebase', shape: 'event',
        surface: '#ffffff', author: '#202124', accent: '#f57c00',
        ink: '#202124', sub: '#5f6368', border: '#e8eaed',
    },

    /* ------------------------------------------------ work managers */
    notion: {
        name: 'Notion', shape: 'notion',
        surface: '#ffffff', author: '#37352f', accent: '#37352f',
        ink: '#37352f', sub: '#787774', border: '#e9e9e7',
    },
    monday: {
        name: 'monday', shape: 'monday',
        surface: '#ffffff', author: '#323338', accent: '#0073ea',
        ink: '#323338', sub: '#676879', border: '#d0d4e4',
    },
    clickup: {
        name: 'ClickUp', shape: 'clickup',
        surface: '#ffffff', author: '#292d34', accent: '#7b68ee',
        ink: '#292d34', sub: '#7c828d', border: '#e9ebf0',
    },
    trello: {
        name: 'Trello', shape: 'trello',
        surface: '#ffffff', author: '#172b4d', accent: '#0079bf',
        ink: '#172b4d', sub: '#6b778c', border: '#dfe1e6',
    },
    asana: {
        name: 'Asana', shape: 'asana',
        surface: '#ffffff', author: '#1e1f21', accent: '#f06a6a',
        ink: '#1e1f21', sub: '#6d6e6f', border: '#e8e8e9',
    },
    todoist: {
        name: 'Todoist', shape: 'todoist',
        surface: '#ffffff', author: '#202020', accent: '#dc4c3e',
        ink: '#202020', sub: '#808080', border: '#eeeeee',
    },

    /* ------------------------------------------------ commerce / billing */
    stripe: {
        name: 'Stripe', shape: 'stripe',
        surface: '#0a2540', author: '#f6f9fc', accent: '#635bff',
        ink: '#f6f9fc', sub: '#8898aa', border: 'rgba(246,249,252,0.12)',
    },
    shopify: {
        name: 'Shopify', shape: 'shopify',
        surface: '#ffffff', author: '#202223', accent: '#008060',
        ink: '#202223', sub: '#6d7175', border: '#e1e3e5',
    },

    /* ------------------------------------------------ scheduling */
    cal_com: {
        name: 'Cal.com', shape: 'booking',
        surface: '#111111', author: '#f9fafb', accent: '#f9fafb',
        ink: '#f9fafb', sub: '#9ca3af', border: 'rgba(249,250,251,0.14)',
    },
    calendly: {
        name: 'Calendly', shape: 'booking',
        surface: '#ffffff', author: '#0b3558', accent: '#006bff',
        ink: '#0b3558', sub: '#476788', border: '#e7edf6',
    },
    zoom: {
        name: 'Zoom', shape: 'booking',
        surface: '#ffffff', author: '#232333', accent: '#0b5cff',
        ink: '#232333', sub: '#6e7180', border: '#e7e8ec',
    },
    google_calendar: {
        name: 'Google Calendar', shape: 'booking',
        surface: '#ffffff', author: '#202124', accent: '#1a73e8',
        ink: '#202124', sub: '#5f6368', border: '#e8eaed',
    },

    /* ------------------------------------------------ forms / tables */
    typeform: {
        name: 'Typeform', shape: 'response',
        surface: '#ffffff', author: '#262627', accent: '#262627',
        ink: '#262627', sub: '#737373', border: '#e5e5e5',
    },
    google_forms: {
        name: 'Google Forms', shape: 'response',
        surface: '#ffffff', author: '#202124', accent: '#7248b9',
        ink: '#202124', sub: '#5f6368', border: '#e8eaed',
    },
    wordpress: {
        name: 'WordPress', shape: 'response',
        surface: '#ffffff', author: '#1d2327', accent: '#21759b',
        ink: '#1d2327', sub: '#646970', border: '#dcdcde',
    },
    webflow: {
        name: 'Webflow', shape: 'response',
        surface: '#ffffff', author: '#171717', accent: '#4353ff',
        ink: '#171717', sub: '#757575', border: '#e5e5e5',
    },
    google_sheets: {
        name: 'Google Sheets', shape: 'sheet',
        surface: '#ffffff', author: '#202124', accent: '#188038',
        ink: '#202124', sub: '#5f6368', border: '#e8eaed',
    },
    airtable: {
        name: 'Airtable', shape: 'sheet',
        surface: '#ffffff', author: '#333333', accent: '#2d7ff9',
        ink: '#333333', sub: '#6b7280', border: '#e5e7eb',
    },

    /* ------------------------------------------------ CRM / support */
    hubspot: {
        name: 'HubSpot', shape: 'record',
        surface: '#ffffff', author: '#33475b', accent: '#ff7a59',
        ink: '#33475b', sub: '#7c98b6', border: '#e5eaf0',
    },
    pipedrive: {
        name: 'Pipedrive', shape: 'record',
        surface: '#ffffff', author: '#26292c', accent: '#08a742',
        ink: '#26292c', sub: '#747678', border: '#e4e6e8',
    },
    salesforce: {
        name: 'Salesforce', shape: 'record',
        surface: '#ffffff', author: '#032d60', accent: '#00a1e0',
        ink: '#032d60', sub: '#706e6b', border: '#e5e5e5',
    },
    zendesk: {
        name: 'Zendesk', shape: 'ticket',
        surface: '#ffffff', author: '#2f3941', accent: '#03363d',
        ink: '#2f3941', sub: '#68737d', border: '#d8dcde',
    },
    intercom: {
        name: 'Intercom', shape: 'ticket',
        surface: '#ffffff', author: '#222222', accent: '#1f8ded',
        ink: '#222222', sub: '#737376', border: '#e6e6e6',
    },

    /* ------------------------------------------------ social */
    reddit: {
        name: 'Reddit', shape: 'post',
        surface: '#ffffff', author: '#1c1c1c', accent: '#ff4500',
        ink: '#1c1c1c', sub: '#7c7c7c', border: '#e5e5e5',
    },
    twitter: {
        name: 'X', shape: 'post',
        surface: '#000000', author: '#e7e9ea', accent: '#1d9bf0',
        ink: '#e7e9ea', sub: '#71767b', border: 'rgba(231,233,234,0.16)',
    },
    facebook: {
        name: 'Facebook', shape: 'post',
        surface: '#ffffff', author: '#050505', accent: '#0866ff',
        ink: '#050505', sub: '#65676b', border: '#e4e6eb',
    },
    instagram: {
        name: 'Instagram', shape: 'post',
        surface: '#ffffff', author: '#262626', accent: '#0095f6',
        ink: '#262626', sub: '#8e8e8e', border: '#efefef',
    },
    youtube: {
        name: 'YouTube', shape: 'post',
        surface: '#0f0f0f', author: '#f1f1f1', accent: '#ff0000',
        ink: '#f1f1f1', sub: '#aaaaaa', border: 'rgba(241,241,241,0.12)',
    },

    /* ------------------------------------------------ files */
    dropbox: {
        name: 'Dropbox', shape: 'file',
        surface: '#ffffff', author: '#1e1919', accent: '#0061ff',
        ink: '#1e1919', sub: '#736c64', border: '#e7e5e4',
    },
    google_drive: {
        name: 'Google Drive', shape: 'file',
        surface: '#ffffff', author: '#202124', accent: '#1a73e8',
        ink: '#202124', sub: '#5f6368', border: '#e8eaed',
    },
};

/** API-suffixed and vendor-prefixed node slugs → their app theme. */
const ALIASES: Record<string, string> = {
    github_rest: 'github',
    github_graphql: 'github',
    microsoft_outlook: 'outlook',
    sms: 'twilio',
    x: 'twitter',
    google_form: 'google_forms',
    sheets: 'google_sheets',
    gcs: 'google_drive',
    onedrive: 'dropbox',
    stripe_billing: 'stripe',
};

export const APP_THEMES: Record<string, AppTheme> = Object.fromEntries(
    Object.entries(APP_THEME_DEFS).map(([slug, t]) => [slug, { ...t, slug }])
);

export function resolveAppTheme(slug?: string | null): AppTheme | undefined {
    if (!slug) return undefined;
    const key = slug.toLowerCase();
    return APP_THEMES[key] ?? APP_THEMES[ALIASES[key] ?? ''];
}
