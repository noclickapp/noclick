import { index, route, type RouteConfig } from '@react-router/dev/routes';

export default [
    index('routes/home.tsx'),
    route('login', 'routes/login.tsx'),
    route('logout', 'routes/logout.ts'),
    // The key proxy: NoClick's API, with the app's key, for the signed-in owner's pages.
    route('api/v1/*', 'routes/api.v1.ts'),
    // Last, so every other path has a route too: middleware runs only for a path that matches one, and the gate (the
    // root route's middleware) must see every request.
    route('*', 'routes/notFound.tsx'),
] satisfies RouteConfig;
