// Usage rows name a model the way its maker writes it, and leave every other kind of usage alone.
import { describe, expect, it } from 'vitest';
import { getDisplayName, modelDisplayName } from './display';

describe('modelDisplayName', () => {
    it.each([
        ['anthropic/claude-sonnet-5-5', 'Claude Sonnet 5.5'],
        ['claude-opus-4-1-20250805', 'Claude Opus 4.1'],
        ['anthropic/claude-3-5-haiku', 'Claude 3.5 Haiku'],
        ['openai/gpt-5.5', 'GPT-5.5'],
        ['gpt-5.6-luna', 'GPT-5.6 Luna'],
        ['openai/gpt-4o-mini', 'GPT-4o Mini'],
        ['openai/gpt-oss-120b', 'GPT-OSS 120B'],
        ['openai/o3-mini', 'o3 Mini'],
        ['google/gemini-2.5-flash', 'Gemini 2.5 Flash'],
        ['x-ai/grok-4', 'Grok 4'],
        ['meta-llama/llama-3.3-70b-instruct', 'Llama 3.3 70B Instruct'],
        ['deepseek/deepseek-chat-v3.1', 'DeepSeek Chat V3.1'],
        ['moonshotai/kimi-k2', 'Kimi K2'],
        ['qwen/qwen3-coder-30b-a3b', 'Qwen3 Coder 30B A3B'],
        ['z-ai/glm-4.6', 'GLM 4.6'],
        ['mistralai/mistral-small:free', 'Mistral Small'],
        ['openrouter/openai/gpt-5.6-luna', 'GPT-5.6 Luna'],
        ['openrouter/~openai/gpt-mini-latest', 'GPT-Mini Latest'],
        ['openrouter/qwen/qwen3.7-plus', 'Qwen3.7 Plus'],
        ['openrouter/poolside/laguna-xs-2.1:free', 'Laguna XS 2.1'],
        ['openrouter/openrouter/free', 'OpenRouter Free'],
        ['opencode/mimo-v2.5-free', 'MiMo V2.5 Free'],
        ['opencode/deepseek-v4-flash-free', 'DeepSeek V4 Flash Free'],
    ])('%s → %s', (id, name) => {
        expect(modelDisplayName(id)).toBe(name);
    });

    it('is null for anything that is not a model', () => {
        for (const id of ['sandbox', 'agent/sandbox', 'instagram/scrape_profile', 'twilio/sms', 'phone_number']) expect(modelDisplayName(id)).toBeNull();
    });
});

describe('getDisplayName', () => {
    it('names every charge from the one table, the builder sentinels included', () => {
        expect(getDisplayName('agent/sandbox')).toBe('Sandbox time');
        expect(getDisplayName('noclick/builder-2')).toBe('AI Builder');
        expect(getDisplayName('apps/build_cache')).toBe('Site build cache');
        expect(getDisplayName('apps/build')).toBe('Site build');
        expect(getDisplayName('apps/build_outputs')).toBe('Site files kept');
        expect(getDisplayName('storage/repo')).toBe('Code storage');
        expect(getDisplayName('storage/repo_clone')).toBe('Code download');
    });

    it('names a family of charges with what its pattern matched', () => {
        expect(getDisplayName('whatsapp/utility')).toBe('WhatsApp message (utility)');
        expect(getDisplayName('reddit_scraping')).toBe('Reddit pages read');
        expect(getDisplayName('machine/small')).toBe('Machine, a day (small)');
    });

    it('names models cleanly, and anything else in words rather than its code', () => {
        expect(getDisplayName('anthropic/claude-sonnet-5-5')).toBe('Claude Sonnet 5.5');
        expect(getDisplayName('gemini/gemini-2.5-flash')).toBe('Gemini 2.5 Flash');
        expect(getDisplayName('groq/openai/gpt-oss-120b')).toBe('GPT-OSS 120B');
        expect(getDisplayName('apify/some_actor')).toBe('Some actor');
    });

    it('resolves Claude Code short names to the model they stand for', () => {
        expect(getDisplayName('haiku')).toMatch(/^Claude Haiku \d/);
    });

    it('names a serverless function by the hardware it ran on', () => {
        expect(getDisplayName('serverless/cpu')).toBe('Code run (CPU)');
        expect(getDisplayName('serverless/a100')).toBe('Code run (A100)');
    });

    it('never shows a code for what production recorded in the last 90 days', () => {
        // usage_subtype values seen in production to 2026-10-17, models among them.
        const seen = ['noclick/builder-1', 'noclick/testing-1', 'gemini/gemini-2.5-flash', 'gpt-4', 'groq/openai/gpt-oss-120b', 'haiku', 'opus', 'sonnet', 'openai/gpt-image-2.5-sunburst', 'apps/build', 'apps/build_cache', 'apps/build_outputs', 'apps/hosting', 'apps/releases', 'browser/minutes', 'database/compute', 'database/history', 'database/rows_read', 'database/rows_written', 'database/storage', 'email/agent_reply', 'email/agent_update', 'email/coordinator', 'email/platform_app', 'email/platform_human', 'email/platform_inbox_reply', 'email/send_node', 'exa/search_api', 'extraction/ai_transcription', 'extraction/ai_video_digest', 'instagram/scrape_profile', 'linkedin/scrape_profile', 'linkedin/search_posts', 'linkedin/search_profiles', 'noclick/transcribe-1', 'perplexity/api', 'reddit_scraping', 'storage/repo', 'storage/repo_clone', 'storage/repo_push', 'twitter/x_api', 'voice/call', 'agent/sandbox', 'serverless/cpu', 'phone_number', 'whatsapp_connection', 'openrouter/~openai/gpt-luna-latest', 'openrouter/openai/gpt-oss-120b', 'openrouter/openrouter/auto-beta', 'openrouter/inclusionai/ling-3.0-flash:free'];
        for (const subtype of seen) {
            const name = getDisplayName(subtype);
            expect(name, subtype).not.toMatch(/[/_]/);
            expect(name, subtype).not.toBe(subtype);
        }
    });
});
