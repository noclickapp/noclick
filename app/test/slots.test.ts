// The app's slots (src/slots.ts) are few and findable: each is declared once, beside its screen
// (`src/screens/<screen>/slots.ts`), under a name that starts with that screen and says where the place is; one that
// several screens draw (a connection's mark) is declared in `src/ui/slots.ts`, under a name of its own that starts
// with no screen's. A slot declared anywhere else, or twice, would be one a host couldn't find or couldn't fill
// reliably. And the app itself fills none: with every slot left alone it is whole, and filling is for whoever hosts it
// (src/custom/, or another app).
import { readdirSync, readFileSync } from 'node:fs';
import { join, relative, resolve } from 'node:path';
import ts from 'typescript';
import { describe, expect, it } from 'vitest';
import { SCAN_S } from './limits';

const APP = resolve(import.meta.dirname, '..');
const SRC = join(APP, 'src');
const TEST_FILE = /\.test\.[cm]?[jt]sx?$/;

interface Use {
    file: string;
    name: string | null;
}

/** Every call of `slot(…)` and `fill(…)` in `files`, by the names the module imported them under from src/slots.ts. */
function uses(files: Record<string, string>): { declared: Use[]; fills: string[] } {
    const declared: Use[] = [];
    const fills: string[] = [];
    for (const [file, text] of Object.entries(files)) {
        const source = ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true, file.endsWith('x') ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
        const names = { slot: new Set<string>(), fill: new Set<string>() };
        for (const statement of source.statements) {
            if (!ts.isImportDeclaration(statement) || !ts.isStringLiteral(statement.moduleSpecifier) || statement.moduleSpecifier.text !== '@/slots') continue;
            const bindings = statement.importClause?.namedBindings;
            if (!bindings || !ts.isNamedImports(bindings)) continue;
            for (const element of bindings.elements) {
                const imported = (element.propertyName ?? element.name).text;
                if (imported === 'slot' || imported === 'fill') names[imported].add(element.name.text);
            }
        }
        const visit = (node: ts.Node) => {
            if (ts.isCallExpression(node) && ts.isIdentifier(node.expression)) {
                const first = node.arguments[0];
                if (names.slot.has(node.expression.text)) declared.push({ file, name: first && ts.isStringLiteral(first) ? first.text : null });
                if (names.fill.has(node.expression.text)) fills.push(file);
            }
            ts.forEachChild(node, visit);
        };
        visit(source);
    }
    return { declared, fills };
}

/** The screens `files` has, by the folders under src/screens/. */
function screensOf(files: Record<string, string>): Set<string> {
    return new Set(Object.keys(files).flatMap((file) => /^src\/screens\/([^/]+)\//.exec(file)?.[1] ?? []));
}

/** Where several screens' slots are declared. */
const SHARED = 'src/ui/slots.ts';

/** What is wrong with how `files` declare and fill slots, as `file: what`. */
function problems(files: Record<string, string>): string[] {
    const { declared, fills } = uses(files);
    const screens = screensOf(files);
    const found: string[] = [];
    const seen = new Map<string, string>();
    for (const { file, name } of declared) {
        const screen = /^src\/screens\/([^/]+)\/slots\.ts$/.exec(file)?.[1];
        if (!screen && file !== SHARED) found.push(`${file}: declares a slot outside a screen's slots.ts`);
        if (name === null) found.push(`${file}: declares a slot whose name isn't written out`);
        else {
            if (!/^[a-z][A-Za-z0-9]*(?:\.[a-z][A-Za-z0-9]*)+$/.test(name)) found.push(`${file}: '${name}' isn't a dotted path of plain words`);
            if (screen && !name.startsWith(`${screen}.`)) found.push(`${file}: '${name}' doesn't start with its screen (${screen}.)`);
            if (file === SHARED && screens.has(name.split('.')[0])) found.push(`${file}: '${name}' starts with a screen's name: declare it in that screen's slots.ts`);
            if (seen.has(name)) found.push(`${file}: '${name}' is declared already, in ${seen.get(name)}`);
            seen.set(name, file);
        }
    }
    for (const file of fills) if (!file.startsWith('src/custom/')) found.push(`${file}: fills a slot (the app fills none; a host does, from src/custom/)`);
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
    it('passes a screen that declares its slots beside itself, and a host that fills them', () => {
        expect(
            problems({
                'src/screens/console/slots.ts': "import { slot } from '@/slots';\nexport const TERMS = slot('console.terms', null);\nexport const MARK = slot('console.connection.mark', null);",
                'src/custom/mine.tsx': "import { fill } from '@/slots';\nimport { TERMS } from '@/screens/console/slots';\nfill(TERMS, null);",
                'src/screens/console/Page.tsx': "import { useSlot } from '@/slots';\nconst slot = (name: string) => name;\nslot('not a slot');",
                'src/ui/slots.ts': "import { slot } from '@/slots';\nexport const MARK = slot('connection.mark', null);",
            }),
        ).toEqual([]);
    });

    it('catches a slot that a host couldn’t find or rely on', () => {
        expect(
            problems({
                'src/screens/console/slots.ts': [
                    "import { slot, slot as place } from '@/slots';",
                    "export const A = slot('console.terms', null);",
                    "export const B = place('console.terms', null);",
                    "export const C = slot('account.plan', null);",
                    "export const D = slot('Console Terms', null);",
                    'export const E = slot(`console.${1}`, null);',
                ].join('\n'),
                'src/screens/console/Page.tsx': "import { fill, slot } from '@/slots';\nconst HERE = slot('console.page.here', null);\nfill(HERE, null);",
                'src/ui/slots.ts': "import { slot } from '@/slots';\nexport const MARK = slot('console.mark', null);",
            }),
        ).toEqual([
            "src/screens/console/slots.ts: 'console.terms' is declared already, in src/screens/console/slots.ts",
            "src/screens/console/slots.ts: 'account.plan' doesn't start with its screen (console.)",
            "src/screens/console/slots.ts: 'Console Terms' isn't a dotted path of plain words",
            "src/screens/console/slots.ts: 'Console Terms' doesn't start with its screen (console.)",
            "src/screens/console/slots.ts: declares a slot whose name isn't written out",
            "src/screens/console/Page.tsx: declares a slot outside a screen's slots.ts",
            "src/ui/slots.ts: 'console.mark' starts with a screen's name: declare it in that screen's slots.ts",
            'src/screens/console/Page.tsx: fills a slot (the app fills none; a host does, from src/custom/)',
        ]);
    });
});

describe('the app', () => {
    it('declares each slot once, beside its screen, and fills none itself', () => {
        const modules = appModules();
        expect(uses(modules).declared.map((use) => use.name).sort()).toEqual([
            'canvas.agentChat',
            'canvas.builder',
            'canvas.clipboard',
            'canvas.frames',
            'canvas.graph.saves',
            'canvas.interface',
            'canvas.note.markdown',
            'canvas.palette',
            'canvas.presence',
            'canvas.runs.fixes',
            'canvas.runs.reads',
            'canvas.runs.results',
            'canvas.runs.saved',
            'canvas.setup',
            'canvas.setup.cover',
            'canvas.setup.mcp',
            'canvas.setup.runtime',
            'canvas.share',
            'canvas.step.accounts',
            'canvas.step.connection',
            'canvas.step.drawing',
            'canvas.step.editing',
            'canvas.step.link',
            'canvas.step.marks',
            'canvas.step.panels',
            'canvas.step.reads',
            'canvas.step.roles',
            'canvas.step.schemas',
            'canvas.step.track',
            'canvas.step.widgets',
            'canvas.testRun',
            'channels.agent.face',
            'chat.approval',
            'chat.build.question',
            'chat.cards.more',
            'chat.connect.email',
            'chat.connect.link',
            'chat.connect.text',
            'chat.note.setup',
            'chat.outOfFunds',
            'chat.places',
            'chat.question.pick',
            'chat.question.step',
            'chat.working',
            'connect.app',
            'connect.model',
            'connection.mark',
            'connections.account.access',
            'connections.account.more',
            'connections.ai',
            'connections.apps',
            'connections.connect',
            'connections.reads',
            'console.cards.issuerForm',
            'console.terms',
            'mcp.client.marks',
            'resources.file.markdown',
            'resources.kinds',
            'resources.number.actions',
            'resources.numbers',
            'settings.billing',
            'settings.developer',
            'settings.developer.olderKeys',
            'settings.members',
            'settings.notifications',
            'settings.phone',
            'settings.popups',
            'settings.skills',
            'settings.skills.editor',
            'settings.skills.share',
            'settings.usage',
            'settings.workstreams',
            'shell.account.around',
            'shell.account.billing',
            'shell.account.items',
            'shell.account.session',
            'shell.account.staff',
            'shell.account.switchTo',
            'shell.banner',
            'shell.foot.balance',
            'shell.foot.card',
            'shell.foot.invite',
            'shell.pages',
            'shell.palette',
            'shell.workspace',
            'usage.billing.alert',
            'usage.billing.balance',
            'usage.billing.planLine',
            'usage.charge.ask',
            'usage.charge.price',
            'usage.charge.run',
            'work.address',
            'work.apps',
            'work.file.preview',
            'work.funds.add',
            'work.harness.mark',
            'work.joinedSpace.typing',
            'work.message.file',
            'work.model.name',
            'work.reply.markdown',
            'work.teamWorkspace',
            'work.toolServer.signIn',
        ]);
        expect(problems(modules).join('\n')).toBe('');
    }, SCAN_S);
});
