// What reaches NoClick around the SDK, file by file: a socket, an untyped API call, a raw network call, or server code
// reading data itself. The open app's guard (sdkOnly.test.ts) runs it over src/; a host of the screens runs it over its
// own app with its own allowlist. Each file's hits are counted and judged against the allowlist, which only shrinks.
import { readdirSync, readFileSync } from 'node:fs';
import { join, relative } from 'node:path';
import ts from 'typescript';

/** Why a file may keep its hits. `pending` is work a later change moves onto the SDK, naming that change. */
export type Kind =
    | 'signed-link'
    | 'proxy'
    | 'auth'
    | 'third-party'
    | 'same-origin-asset'
    | 'telemetry'
    | 'dev-only'
    | 'staff'
    | 'lab'
    /** A keyless page its link opens, on that link's own routes: the link is the capability, so there's no key to
     *  hold, and what it does is NoClick's own for the link's maker (a card's reveal, a signature, a payment). */
    | 'link-page'
    /** A public page every visitor gets from the edge cache: it reads NoClick's public catalog (and runs its anonymous
     *  test runs) with no key and no account, so nothing is the visitor's to hold. */
    | 'marketing-page'
    | 'pending';

export interface Allowed {
    count: number;
    why: Kind;
    /** The change that moves a `pending` file's hits (2 to 6, numbered in the host's plan of the work). */
    chunk?: number;
}

export type Allowlist = Record<string, Allowed>;

const TEST_FILE = /\.(?:test|spec)\.[cm]?[jt]sx?$/;
const SKIPPED_DIRS = new Set(['test', 'tests', 'fixtures', 'node_modules']);
const SOCKET_PACKAGES = new Set(['socket.io-client', 'yjs', 'y-protocols', 'valtio-yjs']);
const SOCKET_MODULE = /(?:^|\/)(?:socket-sender|socket-receiver|socketCall|useSocketEvent|useShareSocket)$|(?:^|\/)lib\/socket\/|^\.\/socket\//;
const SOCKET_CALLS = new Set(['sendEvent', 'sendEventAsync', 'sendEventWithCallback', 'socketCall', 'onSocketEvent', 'useSocketEvent', 'injectWireEvent']);
const HTTP_METHODS = new Set(['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS']);
const SERVER_PACKAGES = /^(?:pg|@supabase\/.+)$/;

/** The event names a socket declares (`ServerToClientEvents` and `ClientToServerEvents` in a generated types file):
 *  a string naming one is a socket use. Names without a `:` (`error`, `response`) are left out: plain words. */
export function socketEventNames(generatedTypes: string, interfaces = ['ServerToClientEvents', 'ClientToServerEvents']): Set<string> {
    const names = new Set<string>();
    const source = ts.createSourceFile('events.ts', generatedTypes, ts.ScriptTarget.Latest, true);
    source.forEachChild((node) => {
        if (!ts.isInterfaceDeclaration(node) || !interfaces.includes(node.name.text)) return;
        for (const member of node.members) {
            const name = member.name && (ts.isStringLiteral(member.name) || ts.isIdentifier(member.name)) ? member.name.text : null;
            if (name?.includes(':')) names.add(name);
        }
    });
    return names;
}

const isServerModule = (file: string) => /\.server\.[cm]?[jt]sx?$/.test(file) || /(?:^|\/)routes\//.test(file);

const specifierOf = (node: ts.Node): string | null =>
    (ts.isImportDeclaration(node) || ts.isExportDeclaration(node)) && node.moduleSpecifier && ts.isStringLiteral(node.moduleSpecifier)
        ? node.moduleSpecifier.text
        : ts.isCallExpression(node) && node.expression.kind === ts.SyntaxKind.ImportKeyword && node.arguments[0] && ts.isStringLiteral(node.arguments[0])
          ? node.arguments[0].text
          : null;

const calleeName = (expression: ts.Expression): string | null =>
    ts.isIdentifier(expression) ? expression.text : ts.isPropertyAccessExpression(expression) ? expression.name.text : null;

/** Each hit in one module, as `what`. */
export function hitsIn(file: string, text: string, eventNames: Set<string> = new Set()): string[] {
    const found: string[] = [];
    const server = isServerModule(file);
    const source = ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true, /\.[cm]?[jt]sx$/.test(file) ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
    const visit = (node: ts.Node) => {
        const specifier = specifierOf(node);
        if (specifier !== null && !(ts.isImportDeclaration(node) && node.importClause?.isTypeOnly)) {
            if (SOCKET_PACKAGES.has(specifier) || SOCKET_MODULE.test(specifier)) found.push(`socket: imports ${specifier}`);
            if (specifier === 'axios') found.push('network: imports axios');
            if (server && SERVER_PACKAGES.test(specifier)) found.push(`server data: imports ${specifier}`);
        }
        if (ts.isCallExpression(node)) {
            const name = calleeName(node.expression);
            if (name && SOCKET_CALLS.has(name)) found.push(`socket: calls ${name}`);
            const first = node.arguments[0];
            if (name === 'request' && first && ts.isStringLiteralLike(first) && HTTP_METHODS.has(first.text)) {
                found.push(`untyped: request('${first.text}', ...)`);
            }
            // The global fetch takes a URL: a call of no arguments is a function of the module's own named fetch.
            const global = ts.isIdentifier(node.expression) || /^(?:window|globalThis|self)$/.test(node.expression.getText(source).split('.')[0]);
            if (name === 'fetch' && global && node.arguments.length > 0) {
                found.push('network: fetch');
            }
            if (name === 'sendBeacon') found.push('network: sendBeacon');
            if (server && name === 'createPool') found.push('server data: createPool');
        }
        if (ts.isNewExpression(node)) {
            const name = calleeName(node.expression);
            if (name === 'XMLHttpRequest' || name === 'EventSource' || name === 'WebSocket') found.push(`network: new ${name}`);
        }
        if (ts.isObjectLiteralExpression(node)) {
            for (const property of node.properties) {
                const key = property.name && (ts.isIdentifier(property.name) || ts.isStringLiteral(property.name)) ? property.name.text : null;
                if (key === 'event_name') found.push('socket: an event_name key');
            }
        }
        if (ts.isStringLiteralLike(node) && !ts.isImportDeclaration(node.parent) && !ts.isExportDeclaration(node.parent)) {
            if (eventNames.has(node.text) && !ts.isLiteralTypeNode(node.parent)) found.push(`socket: names '${node.text}'`);
            if (server && /^\/(?:api|v1)\//.test(node.text)) found.push(`server data: '${node.text}'`);
        }
        ts.forEachChild(node, visit);
    };
    visit(source);
    return found;
}

/** Every module under `dir` (tests, fixtures and test folders aside), by its path from `base`. */
export function modulesUnder(dir: string, base: string): Record<string, string> {
    const files: Record<string, string> = {};
    const collect = (at: string) => {
        for (const entry of readdirSync(at, { withFileTypes: true })) {
            const path = join(at, entry.name);
            if (entry.isDirectory()) {
                if (!SKIPPED_DIRS.has(entry.name)) collect(path);
            } else if (/\.[cm]?[jt]sx?$/.test(entry.name) && !entry.name.endsWith('.d.ts') && !TEST_FILE.test(entry.name)) {
                files[relative(base, path)] = readFileSync(path, 'utf8');
            }
        }
    };
    collect(dir);
    return files;
}

/** Every file's hits, files with none left out. */
export function scan(modules: Record<string, string>, eventNames?: Set<string>): Record<string, string[]> {
    const out: Record<string, string[]> = {};
    for (const [file, text] of Object.entries(modules)) {
        const hits = hitsIn(file, text, eventNames);
        if (hits.length) out[file] = hits;
    }
    return out;
}

/** What's wrong with `allow` against what `scan` found: a file with hits it doesn't list, a count that went up, a count
 *  that went down without the allowlist shrinking with it, an entry for a file with none, a `pending` naming no change. */
export function judge(found: Record<string, string[]>, allow: Allowlist): string[] {
    const wrong: string[] = [];
    for (const [file, hits] of Object.entries(found)) {
        const allowed = allow[file];
        if (!allowed) wrong.push(`${file}: ${hits.length} new (${[...new Set(hits)].join('; ')}): go through the SDK, or list it with why`);
        else if (hits.length > allowed.count) wrong.push(`${file}: ${hits.length} where ${allowed.count} are allowed (${[...new Set(hits)].join('; ')})`);
        else if (hits.length < allowed.count) wrong.push(`${file}: down to ${hits.length} from ${allowed.count}: lower its count in the allowlist`);
    }
    for (const [file, allowed] of Object.entries(allow)) {
        if (!found[file]) wrong.push(`${file}: nothing left to allow: take it out of the allowlist`);
        if (allowed.why === 'pending' && !(allowed.chunk && allowed.chunk >= 2 && allowed.chunk <= 6)) wrong.push(`${file}: pending names no change (2 to 6)`);
        if (allowed.why !== 'pending' && allowed.chunk !== undefined) wrong.push(`${file}: only pending work names a change`);
    }
    return wrong;
}
