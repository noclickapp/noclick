// Client-side JSX transpilation for instant preview.
// Mirrors the backend pipeline (Sucrase + import map + srcdoc assembly) but runs
// entirely in the browser — no backend round-trip needed.

import { useState, useEffect, useRef } from 'react';

const ESM_SH = 'https://esm.sh';
const REACT_VERSION = '19';
const EXTERNAL = 'react,react-dom';
const TAILWIND_CDN = 'https://cdn.tailwindcss.com';
const BUILTIN_SPECIFIERS = new Set(['react', 'react-dom', '@noclick/sdk']);

// Regex to extract npm package specifiers from transpiled code
const IMPORT_RE = /(?:import\s+.*?\s+from\s+|import\s*\(?\s*)['"]([^'"./][^'"]*?)['"]/gs;

// --- Host-mount transform (mirror of backend jsx_transpiler.apply_host_mount) ---
// Lets the node accept BOTH self-mounting code (returned unchanged) and
// Claude-Artifacts-style `export default` components (whose default we mount).
// MUST stay byte-identical in behavior to the Python version — see that file.
// The react-dom/client import is the reliable self-mount tell (createRoot lives
// only there; the Artifacts shape never imports it; the bootstrap imports it too,
// so this stays idempotent). `ReactDOM.render` catches the legacy API. A bare
// `createRoot(` is deliberately NOT matched — it misfires on object methods.
const REACT_MOUNT_RE = /\bReactDOM\s*\.\s*render\s*\(|react-dom\/client/;
// Known limitation: a literal `export default` at a line start inside a template
// literal/string is matched first → graceful error hint, not a crash. Full fix
// needs es-module-lexer (future hardening). Keep in sync with the Python regexes.
const EXPORT_DEFAULT_NAMED_RE = /^\s*export\s+default\s+(?:function|class)\s+([A-Za-z_$][\w$]*)/m;
const EXPORT_BRACE_DEFAULT_RE = /^\s*export\s*\{\s*([A-Za-z_$][\w$]*)\s+as\s+default\s*\}\s*;?/m;
const EXPORT_DEFAULT_RE = /^\s*export\s+default\s+/m;

const HOST_MOUNT_BOOTSTRAP = `
import { createElement as __ncCreateElement } from 'react';
import { createRoot as __ncCreateRoot } from 'react-dom/client';
(function () {
  var el = (typeof document !== 'undefined' && document.getElementById) ? document.getElementById('root') : null;
  if (!el) return;
  var n = el.childElementCount;
  if (typeof n === 'number' && n > 0) return;
  var comp = (typeof __ncDefault !== 'undefined') ? __ncDefault : null;
  var ok = typeof comp === 'function' || (comp && typeof comp === 'object' && comp.$$typeof);
  if (ok) {
    __ncCreateRoot(el).render(__ncCreateElement(comp));
  } else {
    el.innerHTML = '<div style="font-family:system-ui,sans-serif;color:#a1a1aa;padding:1.5rem;font-size:13px;line-height:1.6">This React code does not render anything. Export your component with <code>export default</code> so it can be mounted.</div>';
  }
})();
`;

export function applyHostMount(jsxSource: string): string {
  if (!jsxSource || !jsxSource.trim()) return jsxSource;
  if (REACT_MOUNT_RE.test(jsxSource)) return jsxSource;

  let code: string;
  const named = jsxSource.match(EXPORT_DEFAULT_NAMED_RE);
  if (named) {
    code = jsxSource.replace(EXPORT_DEFAULT_RE, '') + `\nconst __ncDefault = ${named[1]};`;
  } else {
    const brace = jsxSource.match(EXPORT_BRACE_DEFAULT_RE);
    if (brace) {
      code = jsxSource.replace(brace[0], '') + `\nconst __ncDefault = ${brace[1]};`;
    } else if (EXPORT_DEFAULT_RE.test(jsxSource)) {
      code = jsxSource.replace(EXPORT_DEFAULT_RE, 'const __ncDefault = ');
    } else {
      code = jsxSource;
    }
  }
  return code + HOST_MOUNT_BOOTSTRAP;
}

// Cached SDK bundle (loaded once, cleared on HMR so rebuilds take effect)
let sdkDataUri: string | null = null;

if (import.meta.hot) {
  import.meta.hot.dispose(() => { sdkDataUri = null; });
}

async function loadSdkDataUri(): Promise<string> {
  if (sdkDataUri) return sdkDataUri;
  try {
    const resp = await fetch('/noclick-sdk/sdk.esm.js');
    if (!resp.ok) throw new Error(`SDK fetch failed: ${resp.status}`);
    const text = await resp.text();
    const bytes = new TextEncoder().encode(text);
    let binary = '';
    for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]);
    sdkDataUri = `data:text/javascript;base64,${btoa(binary)}`;
  } catch (e) {
    console.error('[useClientTranspile] SDK load failed:', e);
    throw e;
  }
  return sdkDataUri;
}

function extractImports(code: string): Set<string> {
  const packages = new Set<string>();
  let match;
  IMPORT_RE.lastIndex = 0;
  while ((match = IMPORT_RE.exec(code)) !== null) {
    const specifier = match[1];
    let pkgName: string;
    if (specifier.startsWith('@')) {
      const parts = specifier.split('/');
      pkgName = parts.slice(0, 2).join('/');
    } else {
      pkgName = specifier.split('/')[0];
    }
    if (!BUILTIN_SPECIFIERS.has(pkgName)) {
      packages.add(pkgName);
    }
  }
  return packages;
}

function buildImportMap(code: string, sdkUri: string): Record<string, Record<string, string>> {
  const imports: Record<string, string> = {
    'react': `${ESM_SH}/react@${REACT_VERSION}`,
    'react/': `${ESM_SH}/react@${REACT_VERSION}/`,
    'react-dom': `${ESM_SH}/react-dom@${REACT_VERSION}?external=${EXTERNAL}`,
    'react-dom/': `${ESM_SH}/react-dom@${REACT_VERSION}&external=${EXTERNAL}/`,
    'react/jsx-runtime': `${ESM_SH}/react@${REACT_VERSION}/jsx-runtime`,
    '@noclick/sdk': sdkUri,
  };

  const packages = extractImports(code);
  for (const pkg of [...packages].sort()) {
    imports[pkg] = `${ESM_SH}/${pkg}?external=${EXTERNAL}&bundle`;
    if (pkg.startsWith('@')) {
      imports[`${pkg}/`] = `${ESM_SH}/${pkg}&external=${EXTERNAL}&bundle/`;
    }
  }

  return { imports };
}

function buildSrcdoc(code: string, importMap: Record<string, Record<string, string>>): string {
  const importMapJson = JSON.stringify(importMap, null, 2);
  return `<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <script type="importmap">
${importMapJson}
  </script>
  <script src="${TAILWIND_CDN}"></script>
  <style>
    body { margin: 0; }
    #root { min-height: 100vh; }
    .nc-error { color: #f87171; padding: 1rem; font-family: monospace; font-size: 13px; white-space: pre-wrap; }
  </style>
</head>
<body>
  <div id="root"></div>
  <script>
    window.onerror = function(msg, src, line, col, err) {
      if (typeof msg === 'string' && msg.includes('ResizeObserver')) return true;
      var el = document.getElementById('root');
      el.innerHTML = '<div class="nc-error">' + msg + '\\n' + (src || '') + ':' + line + ':' + col + '</div>';
    };
  </script>
  <script type="module">
${code}
  </script>
</body>
</html>`;
}

interface UseClientTranspileResult {
  srcdoc: string;
  error: string | null;
  transpiling: boolean;
}

/**
 * Client-side JSX transpilation hook.
 * Watches jsxSource and produces srcdoc with debouncing.
 * Returns instantly cached srcdoc, updates on source change.
 */
export function useClientTranspile(jsxSource: string, enabled: boolean): UseClientTranspileResult {
  const [srcdoc, setSrcdoc] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [transpiling, setTranspiling] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const lastSourceRef = useRef('');

  useEffect(() => {
    if (!enabled || !jsxSource || jsxSource === lastSourceRef.current) return;

    // Debounce: wait 150ms after last keystroke before transpiling
    clearTimeout(timerRef.current);
    setTranspiling(true);

    timerRef.current = setTimeout(async () => {
      try {
        // Dynamic import to keep Sucrase out of the initial bundle
        const { transform } = await import('sucrase');

        const result = transform(applyHostMount(jsxSource), {
          transforms: ['jsx', 'typescript'],
          jsxRuntime: 'automatic',
          jsxImportSource: 'react',
          production: true,
        });

        const sdkUri = await loadSdkDataUri();
        const importMap = buildImportMap(result.code, sdkUri);
        const html = buildSrcdoc(result.code, importMap);

        lastSourceRef.current = jsxSource;
        setSrcdoc(html);
        setError(null);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setTranspiling(false);
      }
    }, 150);

    return () => clearTimeout(timerRef.current);
  }, [jsxSource, enabled]);

  return { srcdoc, error, transpiling };
}
