/* Per-app visual identity for the rehearsal's native frames: the staged
   trigger and the outcome render in the COLORS and SHAPE of the app they
   represent — WhatsApp's green bubble on its dark chat, a GitHub issue card,
   a Monday item row, a Stripe payment — so non-technical users recognise
   their own tools at a glance. Deliberate brand islands (fixed hex, identical
   in both product themes).

   Every palette is the app's own DARK theme: the rehearsal screen is dark,
   and a white Gmail pane inside it read as a glaring hole (2026-08-10
   report), so each app contributes the dark mode it actually ships.

   `shape` picks the bespoke composition (bespokeFrames.tsx); the palette
   fills it in. Keyed by the backend tool-name slug (`automation-cal-com` →
   `cal_com`) with aliases for API-suffixed types. An app without an entry
   falls back to the neutral structural frames — never a wrong brand. */

export type AppShape =
    | 'bubble'      // WhatsApp / Telegram / iMessage chat
    | 'row'         // Slack / Discord / Teams message row
    | 'email'       // Gmail / Outlook reading pane
    | 'github'      // issue / PR / push / release card
    | 'gitlab'
    | 'linear'      // identifier + priority issue row
    | 'jira'
    | 'notion'      // page with title + content
    | 'monday'      // board item with status pill
    | 'clickup'
    | 'trello'      // card on a list
    | 'asana'       // task row with round check
    | 'todoist'
    | 'stripe'      // payment / invoice / subscription event
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
    /** Human name, for badges inside the bespoke shapes and a11y. */
    name: string;
    shape: AppShape;
    /** The app's own dark surface. */
    surface: string;
    /** "Their message" container (bubble/row hover, Trello's raised card). */
    bubbleIn?: string;
    /** The app's iconic "your message" color (outbound bubble; gradients ok). */
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
    /** Chat wallpaper (CSS background-image) layered over `surface`. */
    wallpaper?: string;
    /** Which corner the inbound bubble's tail cuts; 'none' = uniformly
        rounded (WhatsApp iOS groups its bubbles tailless). Default 'top'. */
    tail?: 'top' | 'bottom' | 'none';
    /** Color of the ✓✓ delivery ticks on the outbound bubble; absent = none. */
    ticks?: string;
    /** Render the app's (inert) composer row under the chat. */
    composer?: boolean;
    /** Stamped from the map key — bespoke frames key sub-variants on it. */
    slug?: string;
}

const APP_THEME_DEFS: Record<string, Omit<AppTheme, 'slug'>> = {
    /* ------------------------------------------------ chat bubbles */
    // WhatsApp iOS dark: NEUTRAL near-black with the faint doodle wallpaper
    // (not the web client's teal-green), neutral gray inbound bubbles, deep
    // green outbound, amber per-contact author names, teal reserved for
    // accents (quote bar / links).
    whatsapp: {
        name: 'WhatsApp', shape: 'bubble',
        surface: '#0a0c0b', bubbleIn: '#212423', bubbleOut: '#134d37',
        author: '#e7a04d', accent: '#06cf9c', ink: '#f2f3f2', sub: '#9a9c9a',
        border: 'rgba(242,243,242,0.07)',
        wallpaper:
            'radial-gradient(ellipse at 25% 20%, rgba(255,255,255,0.035), transparent 55%), radial-gradient(ellipse at 75% 80%, rgba(255,255,255,0.025), transparent 55%)',
        tail: 'none', ticks: '#53bdeb', composer: true,
    },
    // Telegram iOS dark: near-black purple-hazed wallpaper, charcoal inbound,
    // the purple→blue gradient outbound — not the desktop navy.
    telegram: {
        name: 'Telegram', shape: 'bubble',
        surface: '#08070d',
        bubbleIn: '#222126',
        bubbleOut: 'linear-gradient(160deg, #8a63f2 0%, #5b63f5 100%)',
        author: '#9c84f7', accent: '#6ab2f2', ink: '#ffffff',
        sub: 'rgba(255,255,255,0.45)',
        border: 'rgba(255,255,255,0.07)',
        wallpaper:
            'radial-gradient(ellipse at 20% 25%, rgba(122,92,220,0.13), transparent 55%), radial-gradient(ellipse at 80% 75%, rgba(91,99,245,0.10), transparent 55%), radial-gradient(ellipse at 60% 40%, rgba(150,110,230,0.06), transparent 60%)',
        tail: 'bottom', ticks: 'rgba(255,255,255,0.7)', composer: true,
    },
    twilio: {
        name: 'Messages', shape: 'bubble',
        surface: '#000000', bubbleIn: '#26252a', bubbleOut: '#0a84ff',
        author: '#8e8e93', accent: '#0a84ff', ink: '#ffffff', sub: '#8e8e93',
        border: 'rgba(255,255,255,0.08)',
        tail: 'bottom',
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

    /* ------------------------------------------------ email panes (dark) */
    gmail: {
        name: 'Gmail', shape: 'email',
        surface: '#1f1f1f', author: '#e8eaed', accent: '#ea4335',
        ink: '#e8eaed', sub: '#9aa0a6', border: 'rgba(232,234,237,0.12)',
    },
    outlook: {
        name: 'Outlook', shape: 'email',
        surface: '#292929', author: '#ffffff', accent: '#479ef5',
        ink: '#ffffff', sub: '#adadad', border: 'rgba(255,255,255,0.12)',
    },
    mailgun: {
        name: 'Mailgun', shape: 'email',
        surface: '#1c1c1e', author: '#f2f2f4', accent: '#e66065',
        ink: '#f2f2f4', sub: '#98989e', border: 'rgba(242,242,244,0.12)',
    },
    mailchimp: {
        name: 'Mailchimp', shape: 'email',
        surface: '#241c15', author: '#f6f1eb', accent: '#48c4c9',
        ink: '#f6f1eb', sub: '#a89e93', border: 'rgba(246,241,235,0.12)',
    },
    sendgrid: {
        name: 'SendGrid', shape: 'email',
        surface: '#1c1c1e', author: '#f2f2f4', accent: '#51a9f0',
        ink: '#f2f2f4', sub: '#98989e', border: 'rgba(242,242,244,0.12)',
    },
    send_email: {
        name: 'Email', shape: 'email',
        surface: '#1c1c1e', author: '#f4f4f5', accent: '#a1a1aa',
        ink: '#f4f4f5', sub: '#a1a1aa', border: 'rgba(244,244,245,0.12)',
    },

    /* ------------------------------------------------ dev trackers */
    github: {
        name: 'GitHub', shape: 'github',
        surface: '#0d1117', author: '#e6edf3', accent: '#3fb950',
        ink: '#e6edf3', sub: '#7d8590', border: '#30363d',
    },
    gitlab: {
        name: 'GitLab', shape: 'gitlab',
        surface: '#1f1e24', author: '#ececef', accent: '#fc6d26',
        ink: '#ececef', sub: '#89888d', border: 'rgba(236,236,239,0.12)',
    },
    linear: {
        name: 'Linear', shape: 'linear',
        surface: '#191a23', author: '#f7f8f8', accent: '#5e6ad2',
        ink: '#f7f8f8', sub: '#8a8f98', border: 'rgba(247,248,248,0.1)',
    },
    jira: {
        name: 'Jira', shape: 'jira',
        surface: '#1d2125', author: '#b6c2cf', accent: '#579dff',
        ink: '#b6c2cf', sub: '#8c9bab', border: '#333c43',
    },
    sentry: {
        name: 'Sentry', shape: 'alert',
        surface: '#362d59', author: '#f6f6f8', accent: '#e1567c',
        ink: '#f6f6f8', sub: '#a99fce', border: 'rgba(246,246,248,0.14)',
    },
    datadog: {
        name: 'Datadog', shape: 'alert',
        surface: '#1e2231', author: '#e6e8f0', accent: '#9a6bf7',
        ink: '#e6e8f0', sub: '#8b8fa3', border: 'rgba(230,232,240,0.12)',
    },
    pagerduty: {
        name: 'PagerDuty', shape: 'alert',
        surface: '#1c1c1c', author: '#f0f0f0', accent: '#2bc95e',
        ink: '#f0f0f0', sub: '#9b9b9b', border: 'rgba(240,240,240,0.12)',
    },
    supabase: {
        name: 'Supabase', shape: 'event',
        surface: '#1c1c1c', author: '#ededed', accent: '#3ecf8e',
        ink: '#ededed', sub: '#898989', border: 'rgba(237,237,237,0.12)',
    },
    firestore: {
        name: 'Firebase', shape: 'event',
        surface: '#1f1f1f', author: '#e8eaed', accent: '#ffca28',
        ink: '#e8eaed', sub: '#9aa0a6', border: 'rgba(232,234,237,0.12)',
    },

    /* ------------------------------------------------ work managers */
    notion: {
        name: 'Notion', shape: 'notion',
        surface: '#191919', author: '#e6e5e3', accent: '#e6e5e3',
        ink: '#e6e5e3', sub: '#7f7f7c', border: 'rgba(230,229,227,0.09)',
    },
    monday: {
        name: 'monday', shape: 'monday',
        surface: '#181b34', author: '#d5d8df', accent: '#0073ea',
        ink: '#d5d8df', sub: '#9699a6', border: 'rgba(213,216,223,0.12)',
    },
    clickup: {
        name: 'ClickUp', shape: 'clickup',
        surface: '#1e2126', author: '#e6e8ec', accent: '#7b68ee',
        ink: '#e6e8ec', sub: '#9aa1ac', border: 'rgba(230,232,236,0.1)',
    },
    trello: {
        name: 'Trello', shape: 'trello',
        surface: '#1d2125', bubbleIn: '#22272b',
        author: '#b6c2cf', accent: '#579dff',
        ink: '#b6c2cf', sub: '#8c9bab', border: 'rgba(182,194,207,0.12)',
    },
    asana: {
        name: 'Asana', shape: 'asana',
        surface: '#1e1f21', author: '#f5f4f3', accent: '#f06a6a',
        ink: '#f5f4f3', sub: '#a2a0a2', border: 'rgba(245,244,243,0.1)',
    },
    todoist: {
        name: 'Todoist', shape: 'todoist',
        surface: '#1f1f1f', author: '#f5f5f5', accent: '#ff7066',
        ink: '#f5f5f5', sub: '#9b9b9b', border: 'rgba(245,245,245,0.1)',
    },

    /* ------------------------------------------------ commerce / billing */
    stripe: {
        name: 'Stripe', shape: 'stripe',
        surface: '#0a2540', author: '#f6f9fc', accent: '#635bff',
        ink: '#f6f9fc', sub: '#8898aa', border: 'rgba(246,249,252,0.12)',
    },
    shopify: {
        name: 'Shopify', shape: 'shopify',
        surface: '#1a1a1a', author: '#e3e3e3', accent: '#36a874',
        ink: '#e3e3e3', sub: '#8a8a8a', border: 'rgba(227,227,227,0.12)',
    },

    /* ------------------------------------------------ scheduling */
    cal_com: {
        name: 'Cal.com', shape: 'booking',
        surface: '#111111', author: '#f9fafb', accent: '#f9fafb',
        ink: '#f9fafb', sub: '#9ca3af', border: 'rgba(249,250,251,0.14)',
    },
    calendly: {
        name: 'Calendly', shape: 'booking',
        surface: '#14181f', author: '#e8eef7', accent: '#3d8bff',
        ink: '#e8eef7', sub: '#8fa3bc', border: 'rgba(232,238,247,0.12)',
    },
    zoom: {
        name: 'Zoom', shape: 'booking',
        surface: '#16161e', author: '#eef0f5', accent: '#4a8cff',
        ink: '#eef0f5', sub: '#9598a8', border: 'rgba(238,240,245,0.12)',
    },
    google_calendar: {
        name: 'Google Calendar', shape: 'booking',
        surface: '#1f1f1f', author: '#e8eaed', accent: '#8ab4f8',
        ink: '#e8eaed', sub: '#9aa0a6', border: 'rgba(232,234,237,0.12)',
    },

    /* ------------------------------------------------ forms / tables */
    typeform: {
        name: 'Typeform', shape: 'response',
        surface: '#1f1f1f', author: '#f0f0f0', accent: '#f0f0f0',
        ink: '#f0f0f0', sub: '#9b9b9b', border: 'rgba(240,240,240,0.1)',
    },
    google_forms: {
        name: 'Google Forms', shape: 'response',
        surface: '#1f1f1f', author: '#e8eaed', accent: '#a586e8',
        ink: '#e8eaed', sub: '#9aa0a6', border: 'rgba(232,234,237,0.12)',
    },
    wordpress: {
        name: 'WordPress', shape: 'response',
        surface: '#1d2327', author: '#f0f0f1', accent: '#72aee6',
        ink: '#f0f0f1', sub: '#a7aaad', border: 'rgba(240,240,241,0.12)',
    },
    webflow: {
        name: 'Webflow', shape: 'response',
        surface: '#1e1e1e', author: '#f5f5f5', accent: '#6e79ff',
        ink: '#f5f5f5', sub: '#898989', border: 'rgba(245,245,245,0.1)',
    },
    google_sheets: {
        name: 'Google Sheets', shape: 'sheet',
        surface: '#1f1f1f', author: '#e8eaed', accent: '#5bb974',
        ink: '#e8eaed', sub: '#9aa0a6', border: 'rgba(232,234,237,0.14)',
    },
    airtable: {
        name: 'Airtable', shape: 'sheet',
        surface: '#1d2025', author: '#e5e9f0', accent: '#2d7ff9',
        ink: '#e5e9f0', sub: '#9aa4b2', border: 'rgba(229,233,240,0.12)',
    },

    /* ------------------------------------------------ CRM / support */
    hubspot: {
        name: 'HubSpot', shape: 'record',
        surface: '#1d232c', author: '#e6eaf0', accent: '#ff7a59',
        ink: '#e6eaf0', sub: '#8b98a9', border: 'rgba(230,234,240,0.12)',
    },
    pipedrive: {
        name: 'Pipedrive', shape: 'record',
        surface: '#1e2228', author: '#e8eaec', accent: '#2bbd6e',
        ink: '#e8eaec', sub: '#93989e', border: 'rgba(232,234,236,0.12)',
    },
    salesforce: {
        name: 'Salesforce', shape: 'record',
        surface: '#1a2634', author: '#e5ecf3', accent: '#00a1e0',
        ink: '#e5ecf3', sub: '#8d9aa8', border: 'rgba(229,236,243,0.12)',
    },
    zendesk: {
        name: 'Zendesk', shape: 'ticket',
        surface: '#14282c', author: '#e9ebed', accent: '#78cfc5',
        ink: '#e9ebed', sub: '#8a9aa1', border: 'rgba(233,235,237,0.12)',
    },
    intercom: {
        name: 'Intercom', shape: 'ticket',
        surface: '#16171c', author: '#e8e9ec', accent: '#3d8bff',
        ink: '#e8e9ec', sub: '#8f919a', border: 'rgba(232,233,236,0.12)',
    },

    /* ------------------------------------------------ social */
    reddit: {
        name: 'Reddit', shape: 'post',
        surface: '#0b1416', author: '#d7dadc', accent: '#ff4500',
        ink: '#d7dadc', sub: '#818384', border: 'rgba(215,218,220,0.12)',
    },
    twitter: {
        name: 'X', shape: 'post',
        surface: '#000000', author: '#e7e9ea', accent: '#1d9bf0',
        ink: '#e7e9ea', sub: '#71767b', border: 'rgba(231,233,234,0.16)',
    },
    facebook: {
        name: 'Facebook', shape: 'post',
        surface: '#242526', author: '#e4e6eb', accent: '#2d88ff',
        ink: '#e4e6eb', sub: '#b0b3b8', border: 'rgba(228,230,235,0.12)',
    },
    instagram: {
        name: 'Instagram', shape: 'post',
        surface: '#000000', author: '#f5f5f5', accent: '#0095f6',
        ink: '#f5f5f5', sub: '#a8a8a8', border: 'rgba(245,245,245,0.14)',
    },
    youtube: {
        name: 'YouTube', shape: 'post',
        surface: '#0f0f0f', author: '#f1f1f1', accent: '#ff0000',
        ink: '#f1f1f1', sub: '#aaaaaa', border: 'rgba(241,241,241,0.12)',
    },

    /* ------------------------------------------------ files */
    dropbox: {
        name: 'Dropbox', shape: 'file',
        surface: '#1e1d1b', author: '#f7f5f2', accent: '#3984ff',
        ink: '#f7f5f2', sub: '#a9a49e', border: 'rgba(247,245,242,0.12)',
    },
    google_drive: {
        name: 'Google Drive', shape: 'file',
        surface: '#1f1f1f', author: '#e8eaed', accent: '#8ab4f8',
        ink: '#e8eaed', sub: '#9aa0a6', border: 'rgba(232,234,237,0.12)',
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
