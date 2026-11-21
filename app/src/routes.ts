import { index, layout, route, type RouteConfig } from '@react-router/dev/routes';

export default [
    // The signed-in owner's pages, in the app's frame (src/screens/shell): its sidebar, the command palette and a
    // phone's bar.
    layout('routes/shell.tsx', [
        // The account at a glance.
        index('routes/home.tsx'),
        // The account's NoClick to talk to, acting as the app's key.
        route('chat', 'routes/chat.tsx'),
        // The account's spaces, channels, agents and people, acting as the app's key.
        route('work', 'routes/work.tsx'),
        // The apps and accounts its agents and automations act through, acting as the app's key.
        route('connections', 'routes/connections.tsx'),
        // What the account owns and what it costs, acting as the app's key.
        route('resources', 'routes/resources.tsx'),
        // What each thing cost, as it was used, acting as the app's key.
        route('usage', 'routes/usage.tsx'),
        // Settings: Usage, the plan and the spending cap, the owner's email alerts, the way into the console.
        route('settings', 'routes/settings.tsx'),
    ]),
    route('login', 'routes/login.tsx'),
    route('logout', 'routes/logout.ts'),
    // The key proxy: NoClick's API, with the app's key, for the signed-in owner's pages.
    route('api/v1/*', 'routes/api.v1.ts'),
    // NoClick's developer console, acting as the app's key, in a frame of its own.
    route('developers/*', 'routes/developers.tsx'),
    // The console over made-up data, with no account or network: development only (the route answers 404 otherwise).
    route('developers-lab/*', 'routes/developers-lab.tsx'),
    // Resources over made-up data: development only, as the console's lab.
    route('resources-lab', 'routes/resources-lab.tsx'),
    // The chat over made-up data: development only, as the console's lab.
    route('chat-lab', 'routes/chat-lab.tsx'),
    // Work over made-up data: development only, as the console's lab.
    route('work-lab', 'routes/work-lab.tsx'),
    // Connections over made-up data: development only, as the console's lab.
    route('connections-lab', 'routes/connections-lab.tsx'),
    // Usage over made-up data: development only, as the console's lab.
    route('usage-lab', 'routes/usage-lab.tsx'),
    // Settings over made-up data: development only, as the console's lab.
    route('settings-lab', 'routes/settings-lab.tsx'),
    // A workflow step's settings over made-up data: development only, as the console's lab.
    route('step-form-lab', 'routes/step-form-lab.tsx'),
    // Last, so every other path has a route too: middleware runs only for a path that matches one, and the gate (the
    // root route's middleware) must see every request.
    route('*', 'routes/notFound.tsx'),
] satisfies RouteConfig;
