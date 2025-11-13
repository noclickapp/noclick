// Configuration file for default favorite models shown in the model dropdown
// New users will start with these favorites, but can customize their own list using the pin icon
// Model IDs should match exactly as they appear in the models list

export const FAVORITE_MODELS = [
    'claude-code',
    'openrouter/openai/gpt-4-turbo',
    'openrouter/anthropic/claude-sonnet-4.5',
    'openrouter/minimax/minimax-m2',
] as const;

export type FavoriteModelId = typeof FAVORITE_MODELS[number];
