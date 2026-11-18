// The SDK client for server code (loaders and actions that read NoClick before a page renders): it holds the app's
// key. Screens never use it; they call useClient(), whose client goes through the key proxy.
import { NoClick, type ClientOptions } from 'noclick';
import { noclickApiKey, type AppConfig } from './config.server';

export function serverClient(config: AppConfig, options: Omit<ClientOptions, 'apiKey' | 'baseUrl'> = {}): NoClick {
    return new NoClick({ ...options, apiKey: noclickApiKey(), baseUrl: config.apiUrl });
}
