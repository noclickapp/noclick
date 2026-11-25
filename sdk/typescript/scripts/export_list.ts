// Keeps src/index.ts's exports one name per line, in order:
//
//   node --experimental-strip-types scripts/export_list.ts            rewrite it in its one form
//   node --experimental-strip-types scripts/export_list.ts --check    exit 1 when it isn't in that form
//
// Each module's values are one `export { … }` block and its types one `export type { … }` block, the blocks ordered
// by module, the names in each sorted: two changes that each add a name touch different lines, so they merge without
// a conflict. Nothing else is in the file but its opening doc comment.
import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

export const INDEX = fileURLToPath(new URL("../src/index.ts", import.meta.url));

const STATEMENT = /export (type )?\{([^}]*)\} from "([^"]+)";/g;

export function canonical(source: string): string {
  const start = source.indexOf("\nexport ");
  if (!source.startsWith("/**") || start < 0) throw new Error("src/index.ts must open with its doc comment, then its exports");
  const head = source.slice(0, start).trimEnd();
  const body = source.slice(start);
  const left = body.replace(STATEMENT, "").trim();
  if (left) throw new Error(`src/index.ts holds more than export lists: "${left.slice(0, 80)}"`);
  const modules = new Map<string, { values: Set<string>; types: Set<string> }>();
  for (const [, type, names, from] of body.matchAll(STATEMENT)) {
    const own = modules.get(from) ?? { values: new Set(), types: new Set() };
    modules.set(from, own);
    for (const name of names.split(",").map((n) => n.trim()).filter(Boolean)) {
      if (name.includes(" as ")) throw new Error(`export ${name}: export it by its own name`);
      (type ? own.types : own.values).add(name);
    }
  }
  const block = (keyword: string, names: Set<string>, from: string) =>
    names.size ? [`${keyword} {\n${[...names].sort().map((n) => `  ${n},\n`).join("")}} from "${from}";`] : [];
  const blocks = [...modules.keys()].sort().flatMap((from) => {
    const { values, types } = modules.get(from)!;
    return [...block("export", values, from), ...block("export type", types, from)];
  });
  return `${head}\n\n${blocks.join("\n")}\n`;
}

function main(): number {
  const source = readFileSync(INDEX, "utf8");
  const want = canonical(source);
  if (process.argv.includes("--check")) {
    if (source === want) return 0;
    console.error("src/index.ts isn't one name per line in order: run node --experimental-strip-types scripts/export_list.ts");
    return 1;
  }
  writeFileSync(INDEX, want);
  return 0;
}

if (import.meta.url === `file://${process.argv[1]}`) process.exit(main());
