// An error as one line a person reads: on its own, so what shows an error doesn't load the console's pages with it.
import { NoClickError } from 'noclick';

/** The API's message and next step as one line (for inline and toast errors). */
export function errorText(error: unknown): string {
    if (error instanceof NoClickError) return error.nextStep ? `${error.message} ${error.nextStep}` : error.message;
    return error instanceof Error ? error.message : String(error);
}
