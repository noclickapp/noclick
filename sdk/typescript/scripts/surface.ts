// The two clients' public surfaces and how their names pair up: the Python client's as its reference generator
// reads it (`gen_reference.py --surface`), the TypeScript client's as the compiler reads `src/index.ts`. The
// parity test compares them; the docs at noclick.com/docs use the same pairing to show each Python name's
// TypeScript twin.

import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import ts from "typescript";

export const ROOT = fileURLToPath(new URL("..", import.meta.url));

/** Python names TS spells otherwise, as one. */
export const RENAMED: Record<string, string> = {
  Client: "NoClick", // `new NoClick()`
  Error: "NoClickError", // `Error` would shadow the global
  __version__: "VERSION",
};

/** Members TS spells otherwise (`Class.member` to its TS member): the same thing in each language's idiom. */
export const MEMBER_RENAMED: Record<string, string> = {
  "Client.timeout": "timeoutMs", // TS times in milliseconds
  "Client.backoff": "backoffMs",
  "Client.max_backoff": "maxBackoffMs",
  "Queue.len": "size", // like `Map` and `Set`
};

export interface PythonEntry {
  kind: string;
  members: Set<string>;
  /** Its base classes in the same surface, whose differences it inherits. */
  bases: string[];
}

export interface TypeScriptEntry {
  kind: "class" | "interface" | "type" | "function" | "value";
  symbol: ts.Symbol;
  /** Its own members by name, static and instance (`static` says which). */
  members: Map<string, { symbol: ts.Symbol; static: boolean }>;
  /** Members a class has from the JavaScript runtime (an Error's `message`): they meet Python's, never count as extra. */
  runtime: Set<string>;
  bases: string[];
}

export const norm = (name: string) => name.replace(/_+$/, "").replace(/_/g, "").toLowerCase();
const skipped = (name: string) => /^[_#]/.test(name) || name === "prototype" || name === "constructor";

export function pythonSurface(): Map<string, PythonEntry> {
  const python = process.env.PYTHON ?? "python3";
  const out = execFileSync(python, [`${ROOT}../python/scripts/gen_reference.py`, "--surface"], { encoding: "utf8" });
  const raw = JSON.parse(out) as Record<string, { kind: string; bases: string[]; members: string[] }>;
  const members = (name: string, seen = new Set<string>()): string[] => {
    if (seen.has(name) || !raw[name]) return [];
    seen.add(name);
    return [...raw[name].members.filter((m) => !m.startsWith("_")), ...raw[name].bases.flatMap((base) => members(base, seen))];
  };
  return new Map(Object.entries(raw).map(([name, item]) => [name, {
    kind: item.kind, members: new Set(members(name)), bases: item.bases.filter((b) => b in raw),
  }]));
}

/** Deprecated aliases and internals aren't the surface. */
export function hidden(symbol: ts.Symbol): boolean {
  return (symbol.getDeclarations() ?? []).some((decl) => {
    const flags = ts.getCombinedModifierFlags(decl);
    if (flags & (ts.ModifierFlags.Private | ts.ModifierFlags.Protected)) return true;
    return ts.getJSDocTags(decl).some((tag) => tag.tagName.text === "deprecated" || tag.tagName.text === "internal");
  });
}

export interface TypeScriptSurface {
  checker: ts.TypeChecker;
  entries: Map<string, TypeScriptEntry>;
}

export function typeScriptSurface(): TypeScriptSurface {
  const entry = `${ROOT}src/index.ts`;
  const program = ts.createProgram([entry], {
    allowImportingTsExtensions: true, noEmit: true, strict: true, target: ts.ScriptTarget.ES2022,
    module: ts.ModuleKind.ESNext, moduleResolution: ts.ModuleResolutionKind.Bundler,
  });
  const checker = program.getTypeChecker();
  const module = checker.getSymbolAtLocation(program.getSourceFile(entry)!)!;
  const fromRuntime = (p: ts.Symbol) => (p.getDeclarations() ?? []).every((d) => {
    const file = d.getSourceFile();
    return program.isSourceFileDefaultLibrary(file) || program.isSourceFileFromExternalLibrary(file);
  });
  const visible = (type: ts.Type) => checker.getPropertiesOfType(type).filter((p) => !hidden(p) && !skipped(p.getName()));
  const exportedName = new Map<ts.Symbol, string>();
  for (const exported of checker.getExportsOfModule(module)) {
    const symbol = exported.flags & ts.SymbolFlags.Alias ? checker.getAliasedSymbol(exported) : exported;
    exportedName.set(symbol, exported.getName());
  }
  const entries = new Map<string, TypeScriptEntry>();
  for (const [symbol, name] of exportedName) {
    const decl = symbol.getDeclarations()?.[0];
    if (!decl || hidden(symbol)) continue;
    if (ts.isClassDeclaration(decl) || ts.isInterfaceDeclaration(decl)) {
      const declared = checker.getDeclaredTypeOfSymbol(symbol);
      const statics = ts.isClassDeclaration(decl) ? visible(checker.getTypeOfSymbolAtLocation(symbol, decl)) : [];
      const members = new Map<string, { symbol: ts.Symbol; static: boolean }>();
      const runtime = new Set<string>();
      for (const [props, isStatic] of [[visible(declared), false], [statics, true]] as const) {
        for (const p of props) {
          if (fromRuntime(p)) runtime.add(p.getName());
          else if (!members.has(p.getName())) members.set(p.getName(), { symbol: p, static: isStatic });
        }
      }
      // The nearest exported ancestors, through any the module keeps to itself.
      const exportedBases = (type: ts.Type): string[] => (type.isClassOrInterface() ? checker.getBaseTypes(type) : []).flatMap((base) => {
        const baseSymbol = base.getSymbol();
        const baseName = baseSymbol && exportedName.get(baseSymbol);
        return baseName ? [baseName] : exportedBases(base);
      });
      entries.set(name, {
        kind: ts.isClassDeclaration(decl) ? "class" : "interface", symbol, members, runtime, bases: exportedBases(declared),
      });
    } else {
      const kind = ts.isTypeAliasDeclaration(decl) ? "type" : ts.isFunctionDeclaration(decl) ? "function" : "value";
      entries.set(name, { kind, symbol, members: new Map(), runtime: new Set(), bases: [] });
    }
  }
  return { checker, entries };
}

/** Each Python name's TS twin: its rename, the same name, then the idiom's spelling of it (`usage` and `Usage` each meet their own). */
export function pairNames(py: Iterable<string>, tsNames: Iterable<string>): Map<string, string> {
  const tsAll = new Set(tsNames);
  const pyAll = [...py];
  const exact = new Map<string, string>(
    pyAll.map((name): [string, string] => [name, RENAMED[name] ?? name]).filter(([, tsName]) => tsAll.has(tsName)),
  );
  const taken = new Set(exact.values());
  const byNorm = new Map([...tsAll].filter((name) => !taken.has(name)).map((name) => [norm(name), name]));
  const paired = new Map<string, string>();
  for (const name of pyAll) {
    const tsName = exact.get(name) ?? byNorm.get(norm(name));
    if (tsName) paired.set(name, tsName);
  }
  return paired;
}

/** A Python member's TS twin on the paired class (`Agent.from_name` is `fromName`), if it has one. */
export function pairMember(pyClass: string, member: string, tsMembers: Iterable<string>): string | undefined {
  const all = [...tsMembers];
  const camel = member.replace(/_+$/, "").replace(/_([a-z0-9])/g, (_, c: string) => c.toUpperCase());
  // Exact spellings first, so `TOOLS` and `tools` each meet their own.
  for (const candidate of [MEMBER_RENAMED[`${pyClass}.${member}`], member, camel]) if (candidate && all.includes(candidate)) return candidate;
  return all.find((m) => norm(m) === norm(member));
}
