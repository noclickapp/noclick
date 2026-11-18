// The app's screens reach NoClick only through the SDK client they are handed: `/v1` calls over HTTP (streams of
// events included), which this app's server signs with its key and another host of the screens signs its own way. A
// screen that opened a connection of its own (a WebSocket, an EventSource, a socket library) would go around both, so
// nothing under src/ does. What moves while a page is open reaches a screen as frames its host delivers
// (src/sdk/live.ts), never over a connection the screen made.
import { readdirSync, readFileSync } from 'node:fs';
import { join, relative, resolve } from 'node:path';
import ts from 'typescript';
import { describe, expect, it } from 'vitest';

const APP = resolve(import.meta.dirname, '..');
const SRC = join(APP, 'src');
/** What opens a connection from a page. */
const CONNECTORS = new Set(['WebSocket', 'EventSource', 'WebTransport', 'RTCPeerConnection', 'SharedWorker', 'BroadcastChannel']);
/** Packages that open one. */
const SOCKET_PACKAGES = /^(?:socket\.io(?:-client)?|engine\.io(?:-client)?|partysocket|ws|sockjs-client|reconnecting-websocket|y-websocket|y-socket\.io|pusher-js|ably|eventsource|@microsoft\/signalr)$/;
const TEST_FILE = /\.test\.[cm]?[jt]sx?$/;

const packageOf = (specifier: string): string => {
    const segments = specifier.split('/');
    return (specifier.startsWith('@') ? segments.slice(0, 2) : segments.slice(0, 1)).join('/');
};

/** Every connection `files` (path → source) open by themselves, as `file: what`. */
function connections(files: Record<string, string>): string[] {
    const found: string[] = [];
    for (const [file, text] of Object.entries(files)) {
        const source = ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true, file.endsWith('x') ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
        const visit = (node: ts.Node) => {
            // A name used as a value: `new WebSocket(…)`, `window.WebSocket`, `globalThis['EventSource']`. A type
            // (`socket: WebSocket`) opens nothing.
            if (ts.isIdentifier(node) && CONNECTORS.has(node.text) && !ts.isTypeReferenceNode(node.parent) && !ts.isExpressionWithTypeArguments(node.parent)) {
                found.push(`${file}: uses ${node.text}`);
            }
            if (ts.isStringLiteral(node) && CONNECTORS.has(node.text)) found.push(`${file}: names '${node.text}'`);
            const specifier =
                (ts.isImportDeclaration(node) || ts.isExportDeclaration(node)) && node.moduleSpecifier && ts.isStringLiteral(node.moduleSpecifier)
                    ? node.moduleSpecifier.text
                    : ts.isCallExpression(node) && node.expression.kind === ts.SyntaxKind.ImportKeyword && node.arguments[0] && ts.isStringLiteral(node.arguments[0])
                      ? node.arguments[0].text
                      : null;
            if (specifier !== null && SOCKET_PACKAGES.test(packageOf(specifier))) found.push(`${file}: imports ${packageOf(specifier)}`);
            ts.forEachChild(node, visit);
        };
        visit(source);
    }
    return found;
}

function appModules(): Record<string, string> {
    const files: Record<string, string> = {};
    const collect = (dir: string) => {
        for (const entry of readdirSync(dir, { withFileTypes: true })) {
            const path = join(dir, entry.name);
            if (entry.isDirectory()) collect(path);
            else if (/\.(?:[cm]?[jt]sx?)$/.test(entry.name) && !TEST_FILE.test(entry.name)) files[relative(APP, path)] = readFileSync(path, 'utf8');
        }
    };
    collect(SRC);
    return files;
}

describe('the guard', () => {
    it('passes a type, and what only reads the SDK', () => {
        expect(
            connections({
                'src/screens/page.tsx': "import { Agent, type NoClick } from 'noclick';\nexport function close(socket: WebSocket | null) { socket?.close(); }\nclass Mine implements EventSource {}",
            }),
        ).toEqual([]);
    });

    it('catches a connection a screen opens by itself', () => {
        expect(
            connections({
                'src/screens/page.tsx': [
                    "const a = new WebSocket('wss://example.test');",
                    "const b = new window.EventSource('/events');",
                    "const c = (globalThis as any)['WebSocket'];",
                    "import { io } from 'socket.io-client';",
                    "import PartySocket from 'partysocket/react';",
                    "const d = await import('@microsoft/signalr');",
                ].join('\n'),
            }),
        ).toEqual([
            'src/screens/page.tsx: uses WebSocket',
            'src/screens/page.tsx: uses EventSource',
            "src/screens/page.tsx: names 'WebSocket'",
            'src/screens/page.tsx: imports socket.io-client',
            'src/screens/page.tsx: imports partysocket',
            'src/screens/page.tsx: imports @microsoft/signalr',
        ]);
    });
});

describe('the app', () => {
    it('opens no connection of its own from any screen', () => {
        const modules = appModules();
        expect(Object.keys(modules).filter((file) => file.startsWith('src/screens/console/')).length).toBeGreaterThan(100);
        expect(connections(modules).join('\n')).toBe('');
    });

    it('declares no package that opens one', () => {
        const manifest = JSON.parse(readFileSync(join(APP, 'package.json'), 'utf8')) as Record<string, Record<string, string> | undefined>;
        const declared = ['dependencies', 'devDependencies', 'optionalDependencies', 'peerDependencies'].flatMap((section) => Object.keys(manifest[section] ?? {}));
        expect(declared.filter((name) => SOCKET_PACKAGES.test(name))).toEqual([]);
    });
});
