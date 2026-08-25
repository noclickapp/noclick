// E2E (nc bridge) for the CAS Storage dashboard UI: navigates Debug → CAS Storage
// and asserts the global stat cards + flow ranking render (live data via the
// /admin/cas/* endpoints). Requires the Debug feature flag on (internal user);
// otherwise reports {skipped}.
// Run: nc_run_test({ file: "tests/nc/cas-dashboard-ui.test.ts" })
import { nc } from '~/lib/nc';

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const click = (text: string): boolean => {
  const el = nc.dom.qsa('button,[role="tab"],a').find((b) => (b.textContent || '').trim() === text) as HTMLElement | undefined;
  if (el) { el.click(); return true; }
  return false;
};
const hasText = (t: string): boolean => nc.dom.qsa('*').some((el) => (el.textContent || '').includes(t));

export default async function () {
  if (!click('Debug')) return { skipped: 'no Debug tab (feature flag off)' };
  await sleep(400);

  let onCas = false;
  for (let i = 0; i < 12 && !onCas; i++) {
    onCas = click('CAS Storage');
    if (!onCas) await sleep(150);
  }
  if (!onCas) return { skipped: 'no CAS Storage tab in DebugViewer' };

  // The view fetches /admin/cas/* then renders the grouped cards + ranking.
  let rendered = false;
  for (let i = 0; i < 25 && !rendered; i++) {
    rendered = hasText('Dedup ratio') && hasText('Flows by physical footprint');
    if (!rendered) await sleep(200);
  }
  nc.assert.equal(rendered, true, 'CAS Storage dashboard rendered (cards + ranking)');

  // The grouped stat cards from each section should all be present.
  for (const label of ['Dedup ratio', 'Physical (R2)', 'Postgres', 'Chunks', 'Runs (lifetime)']) {
    nc.assert.equal(hasText(label), true, `stat card present: ${label}`);
  }
  // No error banner.
  nc.assert.equal(hasText('Internal access only') || hasText("Couldn't load"), false, 'no access/load error');

  return { ok: true };
}
