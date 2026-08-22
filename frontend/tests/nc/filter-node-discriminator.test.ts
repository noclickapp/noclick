// Verifies the filter node's discriminated-union config: selecting an operation
// shows only that operation's fields (no leaking of unrelated controls), the
// operation picker renders, and the operator field renders as a searchable
// enum dropdown rather than a plain text input. Added with the filter-node
// refactor that converted its flat 13-field config into a discriminated union.

import { nc } from '~/lib/nc';

function visibleFieldKeys(): string[] {
  const set = new Set<string>();
  document.querySelectorAll('[data-field-key]').forEach(el => {
    const k = el.getAttribute('data-field-key');
    if (k) set.add(k);
  });
  return [...set].sort();
}

/** Open the filter node's config and land on the filter_array variant.
 *  Self-healing against harness timing: re-dispatches selection if the panel
 *  never opened, and dismisses the operation picker (it can grab the field
 *  area on mount) by clicking the Filter Array tile. */
async function openFilterArrayFields(id: string) {
  await nc.wait.until(() => {
    if (document.querySelector('[data-field-key]')) return true;
    const tiles = [...document.querySelectorAll('button[data-flat-index]')];
    if (tiles.length) {
      const fa = tiles.find(b => b.textContent?.trim() === 'Filter Array');
      (fa as HTMLElement | undefined)?.click();
    } else {
      nc.nodes.select(id);
    }
    return false;
  }, 12000, 300);
}

export default async function () {
  const filter = nc.nodes.list().find((n: any) => n.type === 'filter');
  nc.assert.truthy(filter, 'a filter node must exist on the canvas');
  if (!filter) throw new Error('filter node not found');
  const id = filter.id;
  const originalOperation = filter.data?.operation ?? 'filter_array';

  // ── filter_array variant ────────────────────────────────────────────────
  nc.nodes.update(id, { operation: 'filter_array' });
  nc.nodes.select(id);
  await openFilterArrayFields(id);

  const arrayFields = visibleFieldKeys();
  for (const f of ['input_data', 'filter_field', 'operator', 'filter_value', 'case_sensitive']) {
    nc.assert.includes(arrayFields, f, `filter_array should show ${f}`);
  }
  for (const f of ['limit', 'offset', 'sort_field', 'sort_order', 'keep_keys', 'remove_keys', 'dedupe_field']) {
    nc.assert.falsy(arrayFields.includes(f), `filter_array must NOT show ${f}`);
  }

  // Operator renders as a searchable enum (its <input> carries data-field-key).
  nc.assert.truthy(
    document.querySelector('input[data-field-key="operator"]'),
    'operator should render as a searchable enum dropdown',
  );

  // ── sort variant ────────────────────────────────────────────────────────
  // Re-issue the update each poll — harness data writes can race a re-render.
  await nc.wait.until(() => {
    if (visibleFieldKeys().includes('sort_order')) return true;
    nc.nodes.update(id, { operation: 'sort' });
    return false;
  }, 10000, 400);

  const sortFields = visibleFieldKeys();
  for (const f of ['input_data', 'sort_field', 'sort_order']) {
    nc.assert.includes(sortFields, f, `sort should show ${f}`);
  }
  for (const f of ['operator', 'filter_value', 'case_sensitive', 'limit', 'keep_keys']) {
    nc.assert.falsy(sortFields.includes(f), `sort must NOT show ${f}`);
  }

  // ── limit variant ───────────────────────────────────────────────────────
  await nc.wait.until(() => {
    if (visibleFieldKeys().includes('limit')) return true;
    nc.nodes.update(id, { operation: 'limit' });
    return false;
  }, 10000, 400);

  const limitFields = visibleFieldKeys();
  for (const f of ['input_data', 'limit', 'offset']) {
    nc.assert.includes(limitFields, f, `limit should show ${f}`);
  }
  for (const f of ['operator', 'sort_field', 'keep_keys', 'dedupe_field']) {
    nc.assert.falsy(limitFields.includes(f), `limit must NOT show ${f}`);
  }

  // Restore the node to its original operation.
  nc.nodes.update(id, { operation: originalOperation });

  return { arrayFields, sortFields, limitFields };
}
