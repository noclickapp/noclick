// Build script: bundles the SDK into ES modules.
// Main entry has zero React dependency. React hooks are a separate entry.

import { build } from 'esbuild';

// Main SDK (no React)
await build({
  entryPoints: ['src/index.ts'],
  outfile: 'dist/sdk.esm.js',
  bundle: true,
  format: 'esm',
  target: 'es2020',
  external: ['react', 'react-dom'],
  minify: false,
});

console.log('SDK built → dist/sdk.esm.js');
