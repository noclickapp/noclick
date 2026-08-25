// Provider types and utilities for AI model providers
// Contains provider enum, metadata mappings, and utility functions

import { ReactNode } from 'react';
import {
    OpenAI, Anthropic, Cohere, Azure, Bedrock, Aws, VertexAI,
    Ai21, XAI, Perplexity, Cerebras, Groq, Together, Fireworks, Anyscale,
    Replicate, DeepInfra, Featherless, DeepSeek, AlibabaCloud, Volcengine,
    Moonshot, Gemini, PaLM, Mistral, HuggingFace, AlephAlpha, Baseten,
    NPLCloud, Ollama, WorkersAI, Voyage, Inference, Nvidia, Novita, Nebius,
    Vercel, IBM, LobeHub, Lambda, Hyperbolic, Friendli, SambaNova, Snowflake,
    AssemblyAI, ElevenLabs, Recraft, Jina, V0, AzureAI, Meta, Dbrx,
    Exa, Fal, Google, Kling
} from '@lobehub/icons';
import OpenRouter from '~/components/icons/OpenRouterIcon';
import { HARNESS_BRANDS } from '~/lib/harnessBrand';

// Helper function to create colored icons - using Avatar variant which typically shows colored logos
const createIcon = (IconComponent: any) => <IconComponent.Avatar size={32} />;
// Compact harness brand mark (from the shared HARNESS_BRANDS registry) at the 32px
// size PROVIDER_METADATA icons render at. The full wordmark is reserved for the
// large node-body icon (see AgentModelIcon).
const harnessMark = (src: string, alt: string) => (
    <img src={src} alt={alt} style={{ width: 32, height: 32, objectFit: 'contain' }} />
);

// Providers that are validated in the LiteLLM validate_environment function
export enum ModelProvider {
    // Major providers
    OPENAI = 'openai',
    ANTHROPIC = 'anthropic',
    COHERE = 'cohere',
    OPENROUTER = 'openrouter',
    
    // Cloud platforms  
    AZURE = 'azure',
    BEDROCK = 'bedrock',
    SAGEMAKER = 'sagemaker',
    VERTEX_AI = 'vertex_ai',
    
    // Specialized AI providers
    AI21 = 'ai21',
    AI21_CHAT = 'ai21_chat',
    XAI = 'xai',
    PERPLEXITY = 'perplexity',
    CEREBRAS = 'cerebras',
    GROQ = 'groq',
    TOGETHER_AI = 'together_ai',
    FIREWORKS_AI = 'fireworks_ai',
    ANYSCALE = 'anyscale',
    REPLICATE = 'replicate',
    DEEPINFRA = 'deepinfra',
    FEATHERLESS_AI = 'featherless_ai',
    DATABRICKS = 'databricks',
    LAMBDA_AI = 'lambda_ai',
    HYPERBOLIC = 'hyperbolic',
    FRIENDLIAI = 'friendliai',
    SAMBANOVA = 'sambanova',
    PREDIBASE = 'predibase',
    SNOWFLAKE = 'snowflake',
    WATSONX = 'watsonx',
    ASSEMBLYAI = 'assemblyai',
    DEEPGRAM = 'deepgram',
    ELEVENLABS = 'elevenlabs',
    RECRAFT = 'recraft',
    JINA_AI = 'jina_ai',
    V0 = 'v0',
    GALADRIEL = 'galadriel',
    TOPAZ = 'topaz',
    EXA_AI = 'exa_ai',
    FAL_AI = 'fal_ai',
    GOOGLE_PSE = 'google_pse',
    
    // Chinese providers
    DEEPSEEK = 'deepseek',
    DASHSCOPE = 'dashscope',
    VOLCENGINE = 'volcengine',
    MOONSHOT = 'moonshot',
    KLING = 'kling',
    
    // Legacy/compatibility
    GEMINI = 'gemini',
    PALM = 'palm',
    MISTRAL = 'mistral',
    CODESTRAL = 'codestral',
    TEXT_COMPLETION_CODESTRAL = 'text-completion-codestral',
    
    // Infrastructure providers
    HUGGINGFACE = 'huggingface',
    ALEPH_ALPHA = 'aleph_alpha',
    BASETEN = 'baseten',
    NLP_CLOUD = 'nlp_cloud',
    OLLAMA = 'ollama',
    OLLAMA_CHAT = 'ollama_chat',
    LM_STUDIO = 'lm_studio',
    CLOUDFLARE = 'cloudflare',
    VOYAGE = 'voyage',
    INFINITY = 'infinity',
    NVIDIA_NIM = 'nvidia_nim',
    NOVITA = 'novita',
    NEBIUS = 'nebius',
    BEDROCK_CONVERSE = 'bedrock_converse',
    OCI = 'oci',
    META_LLAMA = 'meta_llama',
    AZURE_AI = 'azure_ai',
    AZURE_TEXT = 'azure_text',
    FIREWORKS_AI_EMBEDDING_MODELS = 'fireworks_ai-embedding-models',
    
    // Agents
    CODEX = 'codex',
    CLAUDE_CODE = 'claude_code',
    OPENCODE = 'opencode',
    OPENCLAW = 'openclaw',
    HERMES_AGENT = 'hermes_agent',

    // Providers reachable as OpenCode sub-models. Distinct from the primary
    // providers above because they ONLY appear inside the OpenCode picker —
    // they aren't first-class chat-LLM choices for the standalone agent path.
    // Note: `opencode-go/*` sub-models intentionally reuse OPENCODE (same
    // OPENCODE_API_KEY env var, same opencode.ai/auth dashboard — the Go
    // subscription just unlocks a different catalog).
    GITHUB_MODELS = 'github_models',
    NVIDIA = 'nvidia',

    // Gateways
    VERCEL_AI_GATEWAY = 'vercel_ai_gateway',
    DATAROBOT = 'datarobot'
}

// Comprehensive metadata for each provider including visual styling and functional information
export interface ProviderMetadata {
    /** Display name for the provider */
    title: string;
    
    /** Optional description of the provider's capabilities or focus */
    description?: string;
    
    /** React icon component */
    icon: ReactNode;
    
    /** Primary brand color for the provider */
    primaryColor: string;
    
    /** Optional secondary brand color */
    secondaryColor?: string;
    
    /** Text color that works well with the primary color */
    textColor: string;
    
    /** Official provider website URL */
    providerURL: string;
    
    /** API keys required to use this provider - array of alternative key combinations */
    requiredApiKeys?: string[][];
    
    /** Optional API keys that can enhance provider functionality */
    optionalApiKeys?: string[];
    
    /** Whether we allow usage-based billing for this provider */
    allowUsageBased: boolean;
}

// Comprehensive provider metadata mapping
export const PROVIDER_METADATA: Record<ModelProvider, ProviderMetadata> = {
    // Major providers
    [ModelProvider.OPENAI]: {
        title: 'OpenAI',
        description: 'Creator of ChatGPT, GPT-4, and DALL-E',
        icon: createIcon(OpenAI),
        primaryColor: '#000',
        textColor: '#ffffff',
        providerURL: 'https://platform.openai.com/api-keys',
        requiredApiKeys: [['OPENAI_API_KEY']],
        allowUsageBased: true
    },
    [ModelProvider.ANTHROPIC]: {
        title: 'Anthropic',
        description: 'Claude AI models focused on safety and helpfulness',
        icon: createIcon(Anthropic),
        primaryColor: '#d4943a',
        textColor: '#ffffff',
        providerURL: 'https://console.anthropic.com/settings/keys',
        requiredApiKeys: [['ANTHROPIC_API_KEY']],
        allowUsageBased: true
    },
    [ModelProvider.COHERE]: {
        title: 'Cohere',
        description: 'Enterprise-focused language models',
        icon: createIcon(Cohere),
        primaryColor: '#39594c',
        textColor: '#ffffff',
        providerURL: 'https://cohere.ai',
        requiredApiKeys: [['COHERE_API_KEY']],
        allowUsageBased: false
    },
    [ModelProvider.OPENROUTER]: {
        title: 'OpenRouter',
        description: 'Unified API for multiple AI providers',
        icon: createIcon(OpenRouter),
        primaryColor: '#C8FF00',
        textColor: '#ffffff',
        providerURL: 'https://openrouter.ai/settings/keys',
        requiredApiKeys: [['OPENROUTER_API_KEY']],
        allowUsageBased: true
    },
    
    // Cloud platforms
    [ModelProvider.AZURE]: {
        title: 'Azure OpenAI',
        description: 'Microsoft Azure OpenAI Service',
        icon: createIcon(Azure),
        primaryColor: '#0078d4',
        textColor: '#ffffff',
        providerURL: 'https://azure.microsoft.com/en-us/products/ai-services/openai-service',
        requiredApiKeys: [['AZURE_API_KEY', 'AZURE_API_BASE', 'AZURE_API_VERSION']],
        optionalApiKeys: ['AZURE_AD_TOKEN', 'AZURE_API_TYPE'],
        allowUsageBased: false
    },
    [ModelProvider.BEDROCK]: {
        title: 'Amazon Bedrock',
        description: 'AWS managed foundation model service',
        icon: createIcon(Bedrock),
        primaryColor: '#ff9900',
        textColor: '#ffffff',
        providerURL: 'https://aws.amazon.com/bedrock',
        requiredApiKeys: [['AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY', 'AWS_REGION_NAME']],
        optionalApiKeys: ['AWS_BEARER_TOKEN_BEDROCK'],
        allowUsageBased: false
    },
    [ModelProvider.SAGEMAKER]: {
        title: 'Amazon SageMaker',
        description: 'AWS machine learning platform',
        icon: createIcon(Aws),
        primaryColor: '#ff9900',
        textColor: '#ffffff',
        providerURL: 'https://aws.amazon.com/sagemaker',
        requiredApiKeys: [['AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY', 'AWS_REGION_NAME']],
        allowUsageBased: false
    },
    [ModelProvider.VERTEX_AI]: {
        title: 'Google Vertex AI',
        description: 'Google Cloud AI platform',
        icon: createIcon(VertexAI),
        primaryColor: '#4285f4',
        textColor: '#ffffff',
        providerURL: 'https://cloud.google.com/vertex-ai',
        requiredApiKeys: [['GOOGLE_APPLICATION_CREDENTIALS', 'VERTEXAI_PROJECT', 'VERTEXAI_LOCATION']],
        allowUsageBased: false
    },
    
    // Specialized AI providers
    [ModelProvider.AI21]: {
        title: 'AI21 Labs',
        description: 'Advanced language models for enterprises',
        icon: createIcon(Ai21),
        primaryColor: '#7c3aed',
        textColor: '#ffffff',
        providerURL: 'https://ai21.com',
        requiredApiKeys: [['AI21_API_KEY']],
        allowUsageBased: false
    },
    [ModelProvider.AI21_CHAT]: {
        title: 'AI21 Chat',
        description: 'AI21 conversational models',
        icon: createIcon(Ai21),
        primaryColor: '#7c3aed',
        textColor: '#ffffff',
        providerURL: 'https://ai21.com',
        requiredApiKeys: [['AI21_API_KEY']],
        allowUsageBased: false
    },
    [ModelProvider.XAI]: {
        title: 'xAI',
        description: 'Grok AI models by Elon Musk',
        icon: createIcon(XAI),
        primaryColor: '#000000',
        textColor: '#ffffff',
        providerURL: 'https://console.x.ai/team/default/api-keys',
        requiredApiKeys: [['XAI_API_KEY']],
        allowUsageBased: false
    },
    [ModelProvider.PERPLEXITY]: {
        title: 'Perplexity',
        description: 'AI-powered search and reasoning',
        icon: createIcon(Perplexity),
        primaryColor: '#20b2aa',
        textColor: '#ffffff',
        providerURL: 'https://perplexity.ai',
        requiredApiKeys: [['PERPLEXITYAI_API_KEY']],
        allowUsageBased: false
    },
    [ModelProvider.CEREBRAS]: {
        title: 'Cerebras',
        description: 'Ultra-fast AI inference',
        icon: createIcon(Cerebras),
        primaryColor: '#ff6b35',
        textColor: '#ffffff',
        providerURL: 'https://cerebras.net',
        requiredApiKeys: [['CEREBRAS_API_KEY']],
        allowUsageBased: false
    },
    [ModelProvider.GROQ]: {
        title: 'Groq',
        description: 'Lightning-fast AI inference hardware',
        icon: createIcon(Groq),
        primaryColor: '#f55036',
        textColor: '#ffffff',
        providerURL: 'https://console.groq.com/keys',
        requiredApiKeys: [['GROQ_API_KEY']],
        allowUsageBased: false
    },
    [ModelProvider.TOGETHER_AI]: {
        title: 'Together AI',
        description: 'Decentralized cloud for AI',
        icon: createIcon(Together),
        primaryColor: '#8b5cf6',
        textColor: '#ffffff',
        providerURL: 'https://together.ai',
        requiredApiKeys: [['TOGETHERAI_API_KEY']],
        allowUsageBased: false
    },
    [ModelProvider.FIREWORKS_AI]: {
        title: 'Fireworks AI',
        description: 'Production AI inference platform',
        icon: createIcon(Fireworks),
        primaryColor: '#ff4757',
        textColor: '#ffffff',
        providerURL: 'https://fireworks.ai',
        requiredApiKeys: [['FIREWORKS_API_KEY']],
        allowUsageBased: false
    },
    [ModelProvider.ANYSCALE]: {
        title: 'Anyscale',
        description: 'Ray-based AI platform',
        icon: createIcon(Anyscale),
        primaryColor: '#00d2ff',
        textColor: '#ffffff',
        providerURL: 'https://anyscale.com',
        requiredApiKeys: [['ANYSCALE_API_KEY']],
        allowUsageBased: false
    },
    [ModelProvider.REPLICATE]: {
        title: 'Replicate',
        description: 'Run AI models with a cloud API',
        icon: createIcon(Replicate),
        primaryColor: '#000000',
        textColor: '#ffffff',
        providerURL: 'https://replicate.com',
        requiredApiKeys: [['REPLICATE_API_TOKEN']],
        allowUsageBased: false
    },
    [ModelProvider.DEEPINFRA]: {
        title: 'DeepInfra',
        description: 'Serverless GPU inference',
        icon: createIcon(DeepInfra),
        primaryColor: '#6366f1',
        textColor: '#ffffff',
        providerURL: 'https://deepinfra.com',
        requiredApiKeys: [['DEEPINFRA_API_KEY']],
        allowUsageBased: false
    },
    [ModelProvider.FEATHERLESS_AI]: {
        title: 'Featherless AI',
        description: 'High-performance AI inference',
        icon: createIcon(Featherless),
        primaryColor: '#10b981',
        textColor: '#ffffff',
        providerURL: 'https://featherless.ai',
        requiredApiKeys: [['FEATHERLESS_API_KEY']],
        allowUsageBased: false
    },
    
    // Chinese providers
    [ModelProvider.DEEPSEEK]: {
        title: 'DeepSeek',
        description: 'Chinese AI research company',
        icon: createIcon(DeepSeek),
        primaryColor: '#1e40af',
        textColor: '#ffffff',
        providerURL: 'https://platform.deepseek.com/api_keys',
        requiredApiKeys: [['DEEPSEEK_API_KEY']],
        allowUsageBased: false
    },
    [ModelProvider.DASHSCOPE]: {
        title: 'DashScope',
        description: 'Alibaba Cloud AI services',
        icon: createIcon(AlibabaCloud),
        primaryColor: '#ff6a00',
        textColor: '#ffffff',
        providerURL: 'https://dashscope.aliyun.com',
        requiredApiKeys: [['DASHSCOPE_API_KEY']],
        allowUsageBased: false
    },
    [ModelProvider.VOLCENGINE]: {
        title: 'VolcEngine',
        description: 'ByteDance cloud AI platform',
        icon: createIcon(Volcengine),
        primaryColor: '#fe2c55',
        textColor: '#ffffff',
        providerURL: 'https://volcengine.com',
        requiredApiKeys: [['VOLCENGINE_API_KEY'], ['ARK_API_KEY']],
        allowUsageBased: false
    },
    [ModelProvider.MOONSHOT]: {
        title: 'Moonshot AI',
        description: 'Chinese AI startup focused on reasoning',
        icon: createIcon(Moonshot),
        primaryColor: '#7c2d12',
        textColor: '#ffffff',
        providerURL: 'https://moonshot.cn',
        requiredApiKeys: [['MOONSHOT_API_KEY']],
        allowUsageBased: false
    },
    
    // Legacy/compatibility
    [ModelProvider.GEMINI]: {
        title: 'Google Gemini',
        description: 'Google\'s multimodal AI model',
        icon: createIcon(Gemini),
        primaryColor: '#4285f4',
        textColor: '#ffffff',
        // AI Studio key page (makersuite.google.com is the legacy redirect).
        // OpenCode CLI's google provider accepts GEMINI_API_KEY,
        // GOOGLE_GENERATIVE_AI_API_KEY, and GOOGLE_API_KEY (in that
        // lookup order per models.dev); we store the value under
        // GEMINI_API_KEY because that's what litellm uses on the
        // in-process LLM path, and opencode-ai picks it up as a fallback.
        providerURL: 'https://aistudio.google.com/app/apikey',
        requiredApiKeys: [['GEMINI_API_KEY']],
        allowUsageBased: true
    },
    [ModelProvider.PALM]: {
        title: 'Google PaLM',
        description: 'Google\'s Pathways Language Model',
        icon: createIcon(PaLM),
        primaryColor: '#4285f4',
        textColor: '#ffffff',
        providerURL: 'https://cloud.google.com/palm',
        requiredApiKeys: [['PALM_API_KEY']],
        allowUsageBased: false
    },
    [ModelProvider.MISTRAL]: {
        title: 'Mistral AI',
        description: 'European AI company with efficient models',
        icon: createIcon(Mistral),
        primaryColor: '#ff7000',
        textColor: '#ffffff',
        providerURL: 'https://console.mistral.ai/api-keys/',
        requiredApiKeys: [['MISTRAL_API_KEY']],
        allowUsageBased: false
    },
    [ModelProvider.CODESTRAL]: {
        title: 'Codestral',
        description: 'Mistral\'s code-specialized model',
        icon: createIcon(Mistral),
        primaryColor: '#ff7000',
        textColor: '#ffffff',
        providerURL: 'https://mistral.ai',
        requiredApiKeys: [['CODESTRAL_API_KEY']],
        allowUsageBased: false
    },
    [ModelProvider.TEXT_COMPLETION_CODESTRAL]: {
        title: 'Codestral Completion',
        description: 'Mistral\'s text completion model',
        icon: createIcon(Mistral),
        primaryColor: '#ff7000',
        textColor: '#ffffff',
        providerURL: 'https://mistral.ai',
        requiredApiKeys: [['CODESTRAL_API_KEY']],
        allowUsageBased: false
    },
    
    // Infrastructure providers
    [ModelProvider.HUGGINGFACE]: {
        title: 'Hugging Face',
        description: 'Open-source AI model hub',
        icon: createIcon(HuggingFace),
        primaryColor: '#ff9d00',
        textColor: '#ffffff',
        providerURL: 'https://huggingface.co',
        requiredApiKeys: [["HF_TOKEN"]],
        allowUsageBased: false
    },
    [ModelProvider.ALEPH_ALPHA]: {
        title: 'Aleph Alpha',
        description: 'European AI safety-focused company',
        icon: createIcon(AlephAlpha),
        primaryColor: '#000000',
        textColor: '#ffffff',
        providerURL: 'https://aleph-alpha.com',
        requiredApiKeys: [['ALEPH_ALPHA_API_KEY']],
        allowUsageBased: false
    },
    [ModelProvider.BASETEN]: {
        title: 'Baseten',
        description: 'ML infrastructure platform',
        icon: createIcon(Baseten),
        primaryColor: '#6366f1',
        textColor: '#ffffff',
        providerURL: 'https://baseten.co',
        requiredApiKeys: [['BASETEN_API_KEY']],
        allowUsageBased: false
    },
    [ModelProvider.NLP_CLOUD]: {
        title: 'NLP Cloud',
        description: 'Production-ready NLP API',
        icon: createIcon(NPLCloud),
        primaryColor: '#3b82f6',
        textColor: '#ffffff',
        providerURL: 'https://nlpcloud.io',
        requiredApiKeys: [['NLP_CLOUD_API_KEY']],
        allowUsageBased: false
    },
    [ModelProvider.OLLAMA]: {
        title: 'Ollama',
        description: 'Run large language models locally',
        icon: createIcon(Ollama),
        primaryColor: '#000000',
        textColor: '#ffffff',
        providerURL: 'https://ollama.ai',
        requiredApiKeys: [['OLLAMA_API_BASE']],
        allowUsageBased: false
    },
    [ModelProvider.OLLAMA_CHAT]: {
        title: 'Ollama Chat',
        description: 'Local chat interface for Ollama',
        icon: createIcon(Ollama),
        primaryColor: '#000000',
        textColor: '#ffffff',
        providerURL: 'https://ollama.ai',
        requiredApiKeys: [['OLLAMA_API_BASE']],
        allowUsageBased: false
    },
    [ModelProvider.LM_STUDIO]: {
        title: 'LM Studio',
        description: 'Run LLMs locally with GPU acceleration',
        icon: createIcon(LobeHub), // Using generic AI icon as LM Studio not in Lobe icons
        primaryColor: '#6366f1',
        textColor: '#ffffff',
        providerURL: 'https://lmstudio.ai',
        requiredApiKeys: [['LM_STUDIO_API_BASE']],
        optionalApiKeys: ['LM_STUDIO_API_KEY'],
        allowUsageBased: false
    },
    [ModelProvider.CLOUDFLARE]: {
        title: 'Cloudflare Workers AI',
        description: 'Edge AI inference platform',
        icon: createIcon(WorkersAI),
        primaryColor: '#f48120',
        textColor: '#ffffff',
        providerURL: 'https://cloudflare.com/developer-platform/workers-ai',
        requiredApiKeys: [['CLOUDFLARE_API_KEY', 'CLOUDFLARE_ACCOUNT_ID']],
        allowUsageBased: false
    },
    [ModelProvider.VOYAGE]: {
        title: 'Voyage AI',
        description: 'Embedding and retrieval models',
        icon: createIcon(Voyage),
        primaryColor: '#8b5cf6',
        textColor: '#ffffff',
        providerURL: 'https://voyage.ai',
        requiredApiKeys: [['VOYAGE_API_KEY']],
        allowUsageBased: false
    },
    [ModelProvider.INFINITY]: {
        title: 'Infinity',
        description: 'Self-hosted embedding server',
        icon: createIcon(Inference),
        primaryColor: '#6366f1',
        textColor: '#ffffff',
        providerURL: 'https://github.com/michaelfeil/infinity',
        requiredApiKeys: [['INFINITY_API_KEY']],
        allowUsageBased: false
    },
    [ModelProvider.NVIDIA_NIM]: {
        title: 'NVIDIA NIM',
        description: 'NVIDIA\'s AI microservices',
        icon: createIcon(Nvidia),
        primaryColor: '#76b900',
        textColor: '#ffffff',
        providerURL: 'https://nvidia.com/nim',
        requiredApiKeys: [["NVIDIA_NIM_API_KEY"]],
        optionalApiKeys: ['NVIDIA_NIM_API_BASE'],
        allowUsageBased: false
    },
    [ModelProvider.NOVITA]: {
        title: 'Novita AI',
        description: 'GPU cloud for AI inference',
        icon: createIcon(Novita),
        primaryColor: '#ec4899',
        textColor: '#ffffff',
        providerURL: 'https://novita.ai',
        requiredApiKeys: [['NOVITA_API_KEY']],
        allowUsageBased: false
    },
    [ModelProvider.NEBIUS]: {
        title: 'Nebius',
        description: 'AI-focused cloud platform',
        icon: createIcon(Nebius),
        primaryColor: '#3b82f6',
        textColor: '#ffffff',
        providerURL: 'https://nebius.ai',
        requiredApiKeys: [['NEBIUS_API_KEY']],
        allowUsageBased: false
    },
    
    // Agents
    [ModelProvider.CODEX]: {
        title: 'OpenAI Codex',
        description: 'AI coding agent with shell access and file editing',
        icon: createIcon(OpenAI),
        primaryColor: '#000',
        textColor: '#ffffff',
        providerURL: 'https://platform.openai.com/api-keys',
        requiredApiKeys: [['OPENAI_API_KEY']],
        allowUsageBased: false,
    },
    [ModelProvider.CLAUDE_CODE]: {
        title: 'Claude Code',
        description: 'Anthropic coding agent with shell access and file editing',
        icon: createIcon(Anthropic),
        primaryColor: '#D97757',
        textColor: '#ffffff',
        providerURL: 'https://console.anthropic.com/settings/keys',
        requiredApiKeys: [['ANTHROPIC_API_KEY']],
        allowUsageBased: false,
    },
    [ModelProvider.OPENCODE]: {
        title: 'OpenCode',
        description: 'Multi-provider coding agent with shell access and file editing',
        icon: harnessMark(HARNESS_BRANDS.opencode.markSrc, 'OpenCode'),
        primaryColor: '#10b981',
        textColor: '#ffffff',
        providerURL: 'https://opencode.ai/auth',
        // Only the OpenCode Zen API key lives here. OpenCode also runs
        // anthropic/* and openai/* sub-models — but for those, the form
        // routes to the upstream provider's own metadata via
        // inferProviderFromPrefix (see agentCredentialModel.ts), so the
        // user sees the Anthropic / OpenAI field with that provider's
        // dashboard link rather than a generic "pick any of seven keys"
        // form. The wrapper-default (when no opencode_model is selected
        // yet) is OpenCode Zen, which is the typical onboarding path.
        requiredApiKeys: [['OPENCODE_API_KEY']],
        // allowUsageBased=false because OpenCode's CLI receives user-provided
        // keys via env — there is no
        // NoClick-key fallback path, and we don't pay-and-bill upstream
        // tokens for OpenCode runs. Credentials are therefore mandatory,
        // not optional. (Compare with the in-process LLM agent path,
        // where NoClick can call the API itself and bill usage.)
        allowUsageBased: false,
    },
    [ModelProvider.OPENCLAW]: {
        title: 'OpenClaw',
        description: 'Embedded OpenClaw local agent runtime',
        // Compact claw marker for small chrome (dropdown rows, chips). The full
        // wordmark (/icons/openclaw.svg) is reserved for the large node-body icon.
        icon: harnessMark(HARNESS_BRANDS.openclaw.markSrc, 'OpenClaw'),
        primaryColor: '#0f766e',
        textColor: '#ffffff',
        // Default to the OpenRouter dashboard at the bare-wrapper level
        // since OpenClaw routes through OpenRouter for most models. When
        // the user picks a specific openclaw_model (anthropic/*, openai/*,
        // groq/*, …) inferProviderFromPrefix switches the form to that
        // provider's dashboard. Same dynamic-per-sub-model treatment as
        // OpenCode — credentials are always mandatory for the CLI process
        // (no NoClick-key fallback path).
        providerURL: 'https://openrouter.ai/settings/keys',
        requiredApiKeys: [['OPENROUTER_API_KEY']],
        allowUsageBased: false,
    },
    [ModelProvider.HERMES_AGENT]: {
        title: 'Hermes Agent',
        description: 'NousResearch general-purpose agent with 68+ tools: web search, browser, code execution, and more',
        // Compact "H" marker (the wordmark's H glyph) for small chrome — dropdown
        // rows, chips. The full pixel wordmark (/icons/hermes.svg) is reserved for
        // the large node-body icon, mirroring how OpenClaw uses its claw marker.
        icon: harnessMark(HARNESS_BRANDS.hermes.markSrc, 'Hermes'),
        primaryColor: '#7c3aed',
        textColor: '#ffffff',
        // Default to OpenRouter at the bare-wrapper level — Hermes
        // commonly routes through OpenRouter, and a single recommended
        // key is more onboarding-friendly than three "any-of" fields.
        // Sub-model picks (hermes_agent_model = anthropic/*, openai/*,
        // openrouter/*) switch the field via inferProviderFromPrefix —
        // same dynamic-per-sub-model treatment as OpenCode + OpenClaw.
        providerURL: 'https://openrouter.ai/settings/keys',
        requiredApiKeys: [['OPENROUTER_API_KEY']],
        allowUsageBased: false,
    },

    // ── OpenCode sub-model providers ────────────────────────────────────
    // These only surface inside the OpenCode picker — they aren't first-
    // class chat-LLM choices. The OpenCode CLI uses operator-provided
    // upstream credentials, so they are mandatory here.
    //
    // OpenCode Go (a separate subscription tier in OpenCode's picker)
    // intentionally has NO entry here — its sub-models route to
    // ModelProvider.OPENCODE because they share the OPENCODE_API_KEY
    // env var and the same opencode.ai/auth dashboard. Reusing the
    // OPENCODE entry means a user who already added their Zen key
    // doesn't have to re-add it for Go models.
    [ModelProvider.GITHUB_MODELS]: {
        title: 'GitHub Models',
        // Free tier of github.com/marketplace/models. Uses a standard
        // GitHub PAT with the `models:read` scope — no Copilot
        // subscription required. NB the env var is GITHUB_TOKEN (this
        // is also injected by GitHub Actions, which matters if this
        // metadata is reused in a CI environment).
        description: 'Free GitHub-hosted model marketplace (PAT with models:read scope)',
        icon: harnessMark(HARNESS_BRANDS.opencode.markSrc, 'GitHub Models'),
        primaryColor: '#24292e',
        textColor: '#ffffff',
        providerURL: 'https://github.com/settings/tokens',
        requiredApiKeys: [['GITHUB_TOKEN']],
        allowUsageBased: false,
    },
    [ModelProvider.NVIDIA]: {
        title: 'NVIDIA',
        // build.nvidia.com NIM — free credits, hosted Nemotron and
        // other models. Standalone API key (separate from NVIDIA_NIM_API_KEY
        // used elsewhere in PROVIDER_REQUIRED_CREDENTIALS for on-prem NIM).
        description: 'NVIDIA Nemotron and other models via build.nvidia.com (free credits)',
        icon: createIcon(Nvidia),
        primaryColor: '#76b900',
        textColor: '#ffffff',
        providerURL: 'https://build.nvidia.com/settings/api-keys',
        requiredApiKeys: [['NVIDIA_API_KEY']],
        allowUsageBased: false,
    },

    // Gateways
    [ModelProvider.VERCEL_AI_GATEWAY]: {
        title: 'Vercel AI Gateway',
        description: 'Vercel\'s AI model gateway',
        icon: createIcon(Vercel),
        primaryColor: '#000000',
        textColor: '#ffffff',
        providerURL: 'https://vercel.com/ai',
        requiredApiKeys: [['VERCEL_AI_GATEWAY_API_KEY'], ['VERCEL_OIDC_TOKEN']],
        allowUsageBased: false
    },
    [ModelProvider.DATAROBOT]: {
        title: 'DataRobot',
        description: 'Enterprise AI platform',
        icon: createIcon(IBM),
        primaryColor: '#00a1c9',
        textColor: '#ffffff',
        providerURL: 'https://datarobot.com',
        requiredApiKeys: [['DATAROBOT_API_TOKEN']],
        allowUsageBased: false
    },

    // New providers from LiteLLM
    [ModelProvider.DATABRICKS]: {
        title: 'Databricks',
        description: 'Data and AI platform with MLflow integration',
        icon: createIcon(Dbrx),
        primaryColor: '#000000',
        textColor: '#ffffff',
        providerURL: 'https://databricks.com',
        requiredApiKeys: [['DATABRICKS_API_KEY', 'DATABRICKS_API_BASE']],
        allowUsageBased: false
    },
    [ModelProvider.LAMBDA_AI]: {
        title: 'Lambda Labs',
        description: 'High-performance GPU cloud for AI training',
        icon: createIcon(Lambda),
        primaryColor: '#8b5cf6',
        textColor: '#ffffff',
        providerURL: 'https://lambdalabs.com',
        requiredApiKeys: [['LAMBDA_API_KEY']],
        allowUsageBased: false
    },
    [ModelProvider.HYPERBOLIC]: {
        title: 'Hyperbolic',
        description: 'Ultra-fast AI inference platform',
        icon: createIcon(Hyperbolic),
        primaryColor: '#6366f1',
        textColor: '#ffffff',
        providerURL: 'https://hyperbolic.xyz',
        requiredApiKeys: [['HYPERBOLIC_API_KEY']],
        allowUsageBased: false
    },
    [ModelProvider.FRIENDLIAI]: {
        title: 'FriendliAI',
        description: 'Optimized AI serving platform',
        icon: createIcon(Friendli),
        primaryColor: '#10b981',
        textColor: '#ffffff',
        providerURL: 'https://friendli.ai',
        requiredApiKeys: [['FRIENDLI_TOKEN']],
        allowUsageBased: false
    },
    [ModelProvider.SAMBANOVA]: {
        title: 'SambaNova',
        description: 'AI platform with specialized hardware',
        icon: createIcon(SambaNova),
        primaryColor: '#f59e0b',
        textColor: '#ffffff',
        providerURL: 'https://sambanova.ai',
        requiredApiKeys: [['SAMBANOVA_API_KEY']],
        allowUsageBased: false
    },
    [ModelProvider.PREDIBASE]: {
        title: 'Predibase',
        description: 'Serverless fine-tuned LLMs',
        icon: createIcon(LobeHub), // Using generic AI icon as Predibase not in Lobe icons
        primaryColor: '#6366f1',
        textColor: '#ffffff',
        providerURL: 'https://predibase.com',
        requiredApiKeys: [['PREDIBASE_API_KEY', 'PREDIBASE_TENANT_ID']],
        allowUsageBased: false
    },
    [ModelProvider.SNOWFLAKE]: {
        title: 'Snowflake',
        description: 'Cloud data platform with AI capabilities',
        icon: createIcon(Snowflake),
        primaryColor: '#29b5e8',
        textColor: '#ffffff',
        providerURL: 'https://snowflake.com',
        requiredApiKeys: [['SNOWFLAKE_JWT', 'SNOWFLAKE_ACCOUNT_ID']],
        allowUsageBased: false
    },
    [ModelProvider.WATSONX]: {
        title: 'IBM watsonx',
        description: 'IBM\'s enterprise AI platform',
        icon: createIcon(IBM),
        primaryColor: '#0f62fe',
        textColor: '#ffffff',
        providerURL: 'https://ibm.com/watsonx',
        requiredApiKeys: [['WATSONX_URL', 'WATSONX_APIKEY'], ['WATSONX_URL', 'WATSONX_TOKEN']],
        optionalApiKeys: ['WATSONX_PROJECT_ID', 'WATSONX_DEPLOYMENT_SPACE_ID', 'WATSONX_ZENAPIKEY'],
        allowUsageBased: false
    },
    [ModelProvider.ASSEMBLYAI]: {
        title: 'AssemblyAI',
        description: 'Speech-to-text and audio intelligence APIs',
        icon: createIcon(AssemblyAI),
        primaryColor: '#7c3aed',
        textColor: '#ffffff',
        providerURL: 'https://assemblyai.com',
        requiredApiKeys: [['ASSEMBLYAI_API_KEY']],
        allowUsageBased: false
    },
    [ModelProvider.DEEPGRAM]: {
        title: 'Deepgram',
        description: 'Advanced speech recognition and understanding',
        icon: createIcon(Inference), // Using generic AI icon
        primaryColor: '#13ef93',
        textColor: '#000000',
        providerURL: 'https://deepgram.com',
        requiredApiKeys: [['DEEPGRAM_API_KEY']],
        allowUsageBased: false
    },
    [ModelProvider.ELEVENLABS]: {
        title: 'ElevenLabs',
        description: 'AI voice generation and speech synthesis',
        icon: createIcon(ElevenLabs),
        primaryColor: '#000000',
        textColor: '#ffffff',
        providerURL: 'https://elevenlabs.io',
        requiredApiKeys: [['ELEVENLABS_API_KEY']],
        allowUsageBased: false
    },
    [ModelProvider.RECRAFT]: {
        title: 'Recraft',
        description: 'AI image generation and editing platform',
        icon: createIcon(Recraft),
        primaryColor: '#ff6b35',
        textColor: '#ffffff',
        providerURL: 'https://recraft.ai',
        requiredApiKeys: [['RECRAFT_API_KEY']],
        optionalApiKeys: ['RECRAFT_API_BASE'],
        allowUsageBased: false
    },
    [ModelProvider.JINA_AI]: {
        title: 'Jina AI',
        description: 'Multimodal AI and neural search platform',
        icon: createIcon(Jina),
        primaryColor: '#009dff',
        textColor: '#ffffff',
        providerURL: 'https://jina.ai',
        requiredApiKeys: [['JINA_API_KEY']],
        allowUsageBased: false
    },
    [ModelProvider.V0]: {
        title: 'v0',
        description: 'Vercel\'s AI-powered UI generation',
        icon: createIcon(V0),
        primaryColor: '#000000',
        textColor: '#ffffff',
        providerURL: 'https://v0.dev',
        requiredApiKeys: [['V0_API_KEY']],
        allowUsageBased: false
    },
    [ModelProvider.GALADRIEL]: {
        title: 'Galadriel',
        description: 'AI-powered blockchain development',
        icon: createIcon(LobeHub), // Using generic AI icon as Galadriel not in Lobe icons
        primaryColor: '#6366f1',
        textColor: '#ffffff',
        providerURL: 'https://galadriel.com',
        requiredApiKeys: [['GALADRIEL_API_KEY']],
        allowUsageBased: false
    },
    [ModelProvider.TOPAZ]: {
        title: 'Topaz',
        description: 'AI inference platform',
        icon: createIcon(LobeHub), // Using generic AI icon as Topaz not in Lobe icons
        primaryColor: '#f59e0b',
        textColor: '#ffffff',
        providerURL: 'https://topaz.ai',
        requiredApiKeys: [['TOPAZ_API_KEY']],
        allowUsageBased: false
    },
    [ModelProvider.BEDROCK_CONVERSE]: {
        title: 'Amazon Bedrock Converse',
        description: 'AWS Bedrock conversational API',
        icon: createIcon(Bedrock),
        primaryColor: '#ff9900',
        textColor: '#ffffff',
        providerURL: 'https://aws.amazon.com/bedrock',
        requiredApiKeys: [['AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY', 'AWS_REGION_NAME']],
        optionalApiKeys: ['AWS_BEARER_TOKEN_BEDROCK'],
        allowUsageBased: false
    },
    [ModelProvider.OCI]: {
        title: 'Oracle Cloud Infrastructure',
        description: 'Oracle\'s cloud AI services',
        icon: createIcon(Inference), // Using generic AI icon
        primaryColor: '#f80000',
        textColor: '#ffffff',
        providerURL: 'https://cloud.oracle.com',
        requiredApiKeys: [['OCI_API_KEY']],
        allowUsageBased: false
    },
    [ModelProvider.META_LLAMA]: {
        title: 'Meta Llama',
        description: 'Meta\'s large language models',
        icon: createIcon(Meta),
        primaryColor: '#1877f2',
        textColor: '#ffffff',
        providerURL: 'https://llama.meta.com',
        requiredApiKeys: [['LLAMA_API_KEY']],
        allowUsageBased: false
    },
    [ModelProvider.AZURE_AI]: {
        title: 'Azure AI',
        description: 'Microsoft Azure AI services',
        icon: createIcon(AzureAI),
        primaryColor: '#0078d4',
        textColor: '#ffffff',
        providerURL: 'https://azure.microsoft.com/en-us/products/ai-services',
        requiredApiKeys: [['AZURE_AI_API_KEY', 'AZURE_AI_API_BASE']],
        allowUsageBased: false
    },
    [ModelProvider.AZURE_TEXT]: {
        title: 'Azure Text Analytics',
        description: 'Microsoft Azure text analysis services',
        icon: createIcon(AzureAI),
        primaryColor: '#0078d4',
        textColor: '#ffffff',
        providerURL: 'https://azure.microsoft.com/en-us/products/ai-services/text-analytics',
        requiredApiKeys: [['AZURE_TEXT_API_KEY']],
        allowUsageBased: false
    },
    [ModelProvider.FIREWORKS_AI_EMBEDDING_MODELS]: {
        title: 'Fireworks AI Embeddings',
        description: 'Fireworks AI embedding models',
        icon: createIcon(Fireworks),
        primaryColor: '#ff4757',
        textColor: '#ffffff',
        providerURL: 'https://fireworks.ai',
        requiredApiKeys: [['FIREWORKS_API_KEY']],
        allowUsageBased: false
    },

    // Additional providers from LiteLLM with official icons
    [ModelProvider.EXA_AI]: {
        title: 'Exa AI',
        description: 'AI search engine',
        icon: createIcon(Exa),
        primaryColor: '#8b5cf6',
        textColor: '#ffffff',
        providerURL: 'https://exa.ai',
        requiredApiKeys: [['EXA_API_KEY']],
        allowUsageBased: false
    },
    [ModelProvider.FAL_AI]: {
        title: 'Fal AI',
        description: 'Fast AI inference platform',
        icon: createIcon(Fal),
        primaryColor: '#f43f5e',
        textColor: '#ffffff',
        providerURL: 'https://fal.ai',
        requiredApiKeys: [['FAL_API_KEY']],
        allowUsageBased: false
    },
    [ModelProvider.GOOGLE_PSE]: {
        title: 'Google Programmable Search',
        description: 'Google custom search API',
        icon: createIcon(Google),
        primaryColor: '#4285f4',
        textColor: '#ffffff',
        providerURL: 'https://programmablesearchengine.google.com',
        requiredApiKeys: [['GOOGLE_PSE_API_KEY']],
        allowUsageBased: false
    },
    [ModelProvider.KLING]: {
        title: 'Kling AI',
        description: 'Video and image generation by Kuaishou',
        icon: createIcon(Kling),
        primaryColor: '#6c5ce7',
        textColor: '#ffffff',
        providerURL: 'https://klingai.com/global/dev',
        requiredApiKeys: [['KLING_ACCESS_KEY', 'KLING_SECRET_KEY']],
        allowUsageBased: true
    },
};

// Utility functions for working with provider metadata
export const getProviderMetadata = (provider: ModelProvider): ProviderMetadata | undefined => {
    return PROVIDER_METADATA[provider];
};

export const getRequiredApiKeys = (provider: ModelProvider): string[][] => {
    return PROVIDER_METADATA[provider]?.requiredApiKeys || [];
};

export const requiresApiKey = (provider: ModelProvider): boolean => {
    return getRequiredApiKeys(provider).length > 0;
};

export const allowsUsageBasedBilling = (provider: ModelProvider): boolean => {
    return PROVIDER_METADATA[provider]?.allowUsageBased || false;
};

export const getProviderTitle = (provider: ModelProvider): string => {
    return PROVIDER_METADATA[provider]?.title || provider;
};

export const getProviderUrl = (provider: ModelProvider): string => {
    return PROVIDER_METADATA[provider]?.providerURL || '';
};

export const getProviderColors = (provider: ModelProvider): { primary: string; secondary?: string; text: string } => {
    const metadata = PROVIDER_METADATA[provider];
    return {
        primary: metadata?.primaryColor || '#6366f1',
        secondary: metadata?.secondaryColor,
        text: metadata?.textColor || '#ffffff'
    };
};
