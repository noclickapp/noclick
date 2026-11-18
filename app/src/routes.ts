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
    // Last, so every other path has a route too: middleware runs only for a path that matches one, and the gate (the
    // root route's middleware) must see every request.
    route('*', 'routes/notFound.tsx'),
] satisfies RouteConfig;
