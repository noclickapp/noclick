/** Where a server-side model-provider key comes from, for the surfaces that
 *  ask for one (the builder's inline prompt, Settings → OAuth Apps & Keys). */
export const PROVIDER_KEY_SOURCES: Record<string, { label: string; url: string; placeholder?: string }> = {
    OPENROUTER_API_KEY: { label: 'OpenRouter', url: 'https://openrouter.ai/keys', placeholder: 'sk-or-…' },
    OPENAI_API_KEY: { label: 'OpenAI', url: 'https://platform.openai.com/api-keys', placeholder: 'sk-…' },
    ANTHROPIC_API_KEY: { label: 'Anthropic', url: 'https://console.anthropic.com/settings/keys', placeholder: 'sk-ant-…' },
    GEMINI_API_KEY: { label: 'Google AI Studio', url: 'https://aistudio.google.com/app/apikey' },
    GOOGLE_API_KEY: { label: 'Google', url: 'https://aistudio.google.com/app/apikey' },
    GROQ_API_KEY: { label: 'Groq', url: 'https://console.groq.com/keys' },
    XAI_API_KEY: { label: 'xAI', url: 'https://console.x.ai' },
    MISTRAL_API_KEY: { label: 'Mistral', url: 'https://console.mistral.ai/api-keys' },
    DEEPSEEK_API_KEY: { label: 'DeepSeek', url: 'https://platform.deepseek.com/api_keys' },
    WAHOOKS_API_KEY: { label: 'WAHooks', url: 'https://wahooks.com', placeholder: 'your WAHooks API key' },
    DISCORD_BOT_TOKEN: { label: 'Discord bot', url: 'https://discord.com/developers/applications', placeholder: 'bot token from Bot → Token' },
    APIFY_API_TOKEN: { label: 'Apify', url: 'https://console.apify.com/settings/integrations', placeholder: 'apify_api_…' },
    EXA_API_KEY: { label: 'Exa', url: 'https://dashboard.exa.ai/api-keys' },
    PERPLEXITY_API_KEY: { label: 'Perplexity', url: 'https://www.perplexity.ai/settings/api', placeholder: 'pplx-…' },
};

/** "OPENROUTER_API_KEY" → "OpenRouter"; an unlisted "FOO_BAR_API_KEY" → "Foo bar". */
export function providerKeyLabel(envVar: string): string {
    const known = PROVIDER_KEY_SOURCES[envVar];
    if (known) return known.label;
    const stem = envVar.replace(/_(API_KEY|API_TOKEN|TOKEN|KEY)$/, '').toLowerCase().replace(/_/g, ' ');
    return stem.charAt(0).toUpperCase() + stem.slice(1);
}
