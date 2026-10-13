// Public installation destinations and response policy, shared by the route UI
// and server handlers. Authentication stays in pipedriveInstall.server.ts so
// importing a restart link never includes server auth code in the browser.

export const PIPEDRIVE_INSTALL_PATH = '/api/auth/pipedrive/install';
export const PIPEDRIVE_INSTALL_HEADERS = {
    'Cache-Control': 'private, no-store',
    'Referrer-Policy': 'no-referrer',
};
