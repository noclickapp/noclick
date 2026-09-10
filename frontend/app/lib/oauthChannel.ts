// A separate same-origin channel for each connect attempt survives providers
// that sever window.opener without mixing callbacks between credential forms.
export function oauthChannelName(provider: string, attempt: string): string {
    if (
        !/^[a-z0-9_]+$/.test(provider) ||
        !/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(attempt)
    ) {
        throw new Error('Invalid OAuth callback channel');
    }
    return `noclick-oauth:${provider}:${attempt}`;
}
