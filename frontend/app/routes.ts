import { readdirSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { index, route, type RouteConfig } from '@react-router/dev/routes';

// The application still uses Remix's nested-directory + dot-delimited route
// convention. The flat-routes helper ignores nested files without parent route
// modules, so enumerate this edition's one route root directly.
const ROUTE_ROOT = './routes';
const INCLUDE_TEST_ROUTES = process.env.NODE_ENV === 'development';

function isTestRoutePath(relativePath: string): boolean {
    return (
        relativePath === 'test' || relativePath.startsWith(`test${path.sep}`)
    );
}

function routeFiles(directory: string, root: string): string[] {
    return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
        const absolutePath = path.join(directory, entry.name);
        const relativePath = path.relative(root, absolutePath);
        if (!INCLUDE_TEST_ROUTES && isTestRoutePath(relativePath)) return [];
        if (entry.isDirectory()) return routeFiles(absolutePath, root);
        if (
            !entry.name.endsWith('.tsx') ||
            entry.name.includes('.test.') ||
            entry.name.includes('.server.') ||
            entry.name.includes('.client.') ||
            entry.name.includes('.tmp')
        ) {
            return [];
        }
        return [relativePath];
    });
}

function urlPath(file: string): string {
    const literals: string[] = [];
    const escaped = file.replace(/\.tsx$/, '').replace(/\[(.)\]/g, (_, character) => {
        literals.push(character);
        return `\u0000${literals.length - 1}\u0000`;
    });
    return escaped
        .split(/[/.]/)
        .map((segment) => {
            if (segment === '$') return '*';
            if (segment.startsWith('$')) return `:${segment.slice(1)}`;
            return segment;
        })
        .join('/')
        .replace(/\u0000(\d+)\u0000/g, (_, index) => literals[Number(index)]);
}

const root = fileURLToPath(new URL(ROUTE_ROOT, import.meta.url));

export default routeFiles(root, root)
    .sort()
    .map((file) => {
        const modulePath = `${ROUTE_ROOT}/${file}`;
        return file === 'index.tsx'
            ? index(modulePath)
            : route(urlPath(file), modulePath);
    }) satisfies RouteConfig;
