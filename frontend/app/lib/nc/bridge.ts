// Browser-side bridge for the nc debug/testing system.
// Listens for test execution commands from the Vite plugin via HMR WebSocket
// and runs test files via dynamic import or evaluates expressions.

if (import.meta.hot) {
  const claimed = new Set<string>();

  import.meta.hot.on('nc:run', async (data: { id: string; file?: string; expr?: string }) => {
    const { id, file, expr } = data;

    // Prevent duplicate execution across multiple tabs
    if (claimed.has(id)) return;
    claimed.add(id);
    if (claimed.size > 200) {
      const first = claimed.values().next().value;
      if (first) claimed.delete(first);
    }

    try {
      let result: unknown;

      if (file) {
        // Dynamic import with cache busting — Vite transforms .ts files on the fly
        const mod = await import(/* @vite-ignore */ `${file}?t=${Date.now()}`);
        const fn = mod.default;
        if (typeof fn !== 'function') {
          throw new Error(`Test file must export a default async function. Got: ${typeof fn}`);
        }
        result = await fn();
      } else if (expr) {
        // Try as single expression first — parens prevent ASI after `return` on newlines
        // and force a SyntaxError for multi-statement code, triggering the fallback
        const trimmed = expr.trimStart();
        let asyncExpr = `(async () => { return (${trimmed}); })()`;
        try {
          result = await eval(asyncExpr);
        } catch (firstErr) {
          // If syntax error, treat as multi-statement block — eval() captures last expression value
          if (firstErr instanceof SyntaxError) {
            asyncExpr = `(async () => { return eval(${JSON.stringify(trimmed)}); })()`;
            result = await eval(asyncExpr);
          } else {
            throw firstErr;
          }
        }
      } else {
        throw new Error('Must provide file or expr');
      }

      // Serialize — strip non-JSON-safe values
      const serialized = result !== undefined ? JSON.parse(JSON.stringify(result)) : null;
      import.meta.hot!.send('nc:result', { id, result: serialized });
    } catch (err) {
      const error = err instanceof Error
        ? `${err.message}${err.stack ? '\n' + err.stack : ''}`
        : String(err);
      import.meta.hot!.send('nc:result', { id, error });
    }
  });
}
