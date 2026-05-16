// Unit test for describeNodeError — the humanizer behind the background-run
// error toast. Pins the two actionable patterns (unset workflow variable,
// missing upstream output) and the raw-error fallback.
//
// Run: mcp__nc__nc_run_test({ file: "tests/nc/describe-node-error.test.ts" })

import { nc } from '~/lib/nc';
import { describeNodeError } from '~/lib/describeNodeError';

export default async function () {
    const out: Record<string, unknown> = {};

    // ── Unresolved {{vars.X}} → setup-oriented guidance ──────────────────
    const varCase = describeNodeError(
        'Sheets Configured?',
        "[ConditionalNode] Input data reference '{{vars.Sheets-Cred}}' was not resolved. "
        + 'Make sure the upstream node has executed and the path is correct.',
    );
    out.varCase = varCase;
    nc.assert.equal(varCase.title, 'Setup may be needed', 'variable case → setup title');
    nc.assert.truthy(varCase.description.includes('Sheets-Cred'), 'names the missing variable');
    nc.assert.truthy(/setup/i.test(varCase.description), 'tells the user to complete Setup');
    nc.assert.falsy(varCase.description.includes('{{'), 'raw template syntax is not shown');

    // ── Unresolved {{node.field}} → upstream-node guidance ───────────────
    const refCase = describeNodeError(
        'Send Email',
        "Input data reference '{{read_sheet.rows}}' was not resolved.",
    );
    out.refCase = refCase;
    nc.assert.equal(refCase.title, 'Missing an input', 'node-ref case → missing-input title');
    nc.assert.truthy(refCase.description.includes('read_sheet.rows'), 'names the missing upstream ref');
    nc.assert.truthy(/upstream/i.test(refCase.description), 'tells the user to run upstream nodes');

    // ── Unknown error → raw passthrough (no information lost) ────────────
    const rawCase = describeNodeError('HTTP Request', 'connect ECONNREFUSED 10.0.0.1:443');
    out.rawCase = rawCase;
    nc.assert.equal(rawCase.title, 'HTTP Request failed', 'unknown error keeps the node-name title');
    nc.assert.equal(rawCase.description, 'connect ECONNREFUSED 10.0.0.1:443', 'unknown error falls back to raw text');

    out.ok = true;
    return out;
}
