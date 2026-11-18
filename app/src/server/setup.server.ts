// What the key proxy's paths answer while a setting is missing or unusable: the API's JSON error, naming the settings
// to fix (never a value). Pages get the setup page instead (src/screens/setup/SetupScreen.tsx).
import type { ConfigProblem } from './config.server';
import { apiError } from './responses.server';

export const SETUP_HOW = 'Set them as environment variables where the app runs (your host’s settings; on your own machine, see .env.example), then restart the app.';

export function setupApiError(problems: ConfigProblem[]): Response {
    return apiError(503, {
        type: 'not_available',
        message: `This app isn’t set up yet: ${problems.map((p) => `${p.name} ${p.problem}`).join(' ')}`,
        next_step: SETUP_HOW,
        missing: problems.map((p) => p.name),
    });
}
