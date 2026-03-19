// Build script: bundles the SDK into a single ES module.
// React is external (resolved by iframe import map or installed as peer dep).
// socket.io-client is external (installed separately for WebSocket transport).

import { build } from 'esbuild';

await build({
  entryPoints: ['src/index.ts'],
  outfile: 'dist/sdk.esm.js',
  bundle: true,
  format: 'esm',
  target: 'es2020',
  external: ['react', 'react-dom', 'socket.io-client'],
  minify: false,
});

console.log('SDK built → dist/sdk.esm.js');
