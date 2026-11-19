import { index, route, type RouteConfig } from '@react-router/dev/routes';

export default [
    index('routes/home.tsx'),
    route('login', 'routes/login.tsx'),
    route('logout', 'routes/logout.ts'),
    // The key proxy: NoClick's API, with the app's key, for the signed-in owner's pages.
    route('api/v1/*', 'routes/api.v1.ts'),
    // NoClick's developer console, acting as the app's key.
    route('developers/*', 'routes/developers.tsx'),
    // The console over made-up data, with no account or network: development only (the route answers 404 otherwise).
    route('developers-lab/*', 'routes/developers-lab.tsx'),
    // What the account owns and what it costs, acting as the app's key.
    route('resources', 'routes/resources.tsx'),
    // Resources over made-up data: development only, as the console's lab.
    route('resources-lab', 'routes/resources-lab.tsx'),
    // The account's spaces, channels, agents and people, acting as the app's key.
    route('work', 'routes/work.tsx'),
    // Work over made-up data: development only, as the console's lab.
    route('work-lab', 'routes/work-lab.tsx'),
    // Last, so every other path has a route too: middleware runs only for a path that matches one, and the gate (the
    // root route's middleware) must see every request.
    route('*', 'routes/notFound.tsx'),
] satisfies RouteConfig;
