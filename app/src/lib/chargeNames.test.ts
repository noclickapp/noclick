// Charges are named from one table, a model the way its maker writes it, and every other kind of usage in words.
import { afterEach, describe, expect, it } from 'vitest';
import { chargeName, modelDisplayName, setModelAliases } from './chargeNames';

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

describe('chargeName', () => {
    afterEach(() => setModelAliases({}));

    it('names every charge from the one table, the builder sentinels included', () => {
        expect(chargeName('agent/sandbox')).toBe('Sandbox time');
        expect(chargeName('noclick/builder-2')).toBe('AI Builder');
        expect(chargeName('apps/build_cache')).toBe('Site build cache');
        expect(chargeName('apps/build')).toBe('Site build');
        expect(chargeName('apps/build_outputs')).toBe('Site files kept');
        expect(chargeName('storage/repo')).toBe('Code storage');
        expect(chargeName('storage/repo_clone')).toBe('Code download');
    });

    it('names a family of charges with what its pattern matched', () => {
        expect(chargeName('whatsapp/utility')).toBe('WhatsApp message (utility)');
        expect(chargeName('reddit_scraping')).toBe('Reddit pages read');
        expect(chargeName('machine/small')).toBe('Machine, a day (small)');
    });

    it('names models cleanly, and anything else in words rather than its code', () => {
        expect(chargeName('anthropic/claude-sonnet-5-5')).toBe('Claude Sonnet 5.5');
        expect(chargeName('gemini/gemini-2.5-flash')).toBe('Gemini 2.5 Flash');
        expect(chargeName('groq/openai/gpt-oss-120b')).toBe('GPT-OSS 120B');
        expect(chargeName('apify/some_actor')).toBe('Some actor');
    });

    it('reads a coding agent’s short name as the model its host says it stands for, else in words', () => {
        expect(chargeName('haiku')).toBe('Haiku');
        setModelAliases({ haiku: 'claude-haiku-9-1' });
        expect(chargeName('haiku')).toBe('Claude Haiku 9.1');
    });

    it('names a serverless function by the hardware it ran on', () => {
        expect(chargeName('serverless/cpu')).toBe('Code run (CPU)');
        expect(chargeName('serverless/a100')).toBe('Code run (A100)');
    });

    it('never shows a code for a kind of charge NoClick records', () => {
        // Kinds of charge NoClick records, models and a coding agent's short names among them.
        const seen = ['noclick/builder-1', 'noclick/testing-1', 'gemini/gemini-2.5-flash', 'gpt-4', 'groq/openai/gpt-oss-120b', 'haiku', 'opus', 'sonnet', 'openai/gpt-image-2.5-sunburst', 'apps/build', 'apps/build_cache', 'apps/build_outputs', 'apps/hosting', 'apps/releases', 'browser/minutes', 'database/compute', 'database/history', 'database/rows_read', 'database/rows_written', 'database/storage', 'email/agent_reply', 'email/agent_update', 'email/coordinator', 'email/platform_app', 'email/platform_human', 'email/platform_inbox_reply', 'email/send_node', 'exa/search_api', 'extraction/ai_transcription', 'extraction/ai_video_digest', 'instagram/scrape_profile', 'linkedin/scrape_profile', 'linkedin/search_posts', 'linkedin/search_profiles', 'noclick/transcribe-1', 'perplexity/api', 'reddit_scraping', 'storage/repo', 'storage/repo_clone', 'storage/repo_push', 'twitter/x_api', 'voice/call', 'agent/sandbox', 'serverless/cpu', 'phone_number', 'whatsapp_connection', 'openrouter/~openai/gpt-luna-latest', 'openrouter/openai/gpt-oss-120b', 'openrouter/openrouter/auto-beta', 'openrouter/inclusionai/ling-3.0-flash:free'];
        setModelAliases({ haiku: 'claude-haiku-9-1', opus: 'claude-opus-9-1', sonnet: 'claude-sonnet-9-1' });
        for (const subtype of seen) {
            const name = chargeName(subtype);
            expect(name, subtype).not.toMatch(/[/_]/);
            expect(name, subtype).not.toBe(subtype);
        }
    });
});
