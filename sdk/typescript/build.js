// Builds the package: the client (dist/index.js, with its declarations in
// dist/types) and the bridge custom interface components load (dist/sdk.esm.js,
// which the backend also serves to their iframes). `node build.js embed` builds
// only the bridge, for the pre-commit hook.
// React is external (resolved by the iframe import map or the npm peer).

import { build } from 'esbuild';
import { execFileSync } from 'node:child_process';
import { readdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

await build({
  entryPoints: ['src/embed/index.ts'],
  outfile: 'dist/sdk.esm.js',
  bundle: true,
  format: 'esm',
  target: 'es2020',
  external: ['react', 'react-dom'],
  minify: false,
  // The client's tsconfig (strict, ES2022 class fields) is not the bridge's.
  tsconfigRaw: {},
});
console.log('Bridge built → dist/sdk.esm.js');

if (process.argv[2] !== 'embed') {
  await build({
    entryPoints: ['src/index.ts'],
    outfile: 'dist/index.js',
    bundle: true,
    format: 'esm',
    platform: 'neutral',
    target: 'es2022',
    minify: false,
  });

  // `npx noclick`: the command line, with its spec (the Python package's JSON files) bundled in.
  await build({
    entryPoints: ['src/cli/bin.ts'],
    outfile: 'dist/cli.js',
    bundle: true,
    format: 'esm',
    platform: 'node',
    target: 'node20',
    minify: false,
  });

  rmSync('dist/types', { recursive: true, force: true });
  execFileSync(join('node_modules', '.bin', 'tsc'), ['-p', 'tsconfig.build.json'], { stdio: 'inherit' });
  // The source imports its siblings as `./x.ts`; a published declaration names them `./x.js`.
  for (const name of readdirSync('dist/types')) {
    const path = join('dist/types', name);
    writeFileSync(path, readFileSync(path, 'utf8').replace(/(["'])(\.\.?\/[^"']+)\.ts\1/g, '$1$2.js$1'));
  }
  console.log('Client built → dist/index.js, dist/types/, dist/cli.js');
}
