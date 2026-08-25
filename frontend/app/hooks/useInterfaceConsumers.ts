// Hook that finds which interface-html-react nodes reference a given workflow
// node by bare ID inside their jsx_source / content. SDK-based interfaces
// reference other nodes through code rather than canvas edges, so an isolated
// node feeding an interface looks orphaned. This powers the "Used by interface"
// badge that makes that hidden dependency visible on the canvas.

import { useCallback } from 'react';
import { useStore } from '@xyflow/react';
import { codeReferencesNodeId } from '~/lib/nodeIdReferences';

export interface InterfaceConsumer {
  id: string;
  label: string;
}

const INTERFACE_HTML_REACT = 'interface-html-react';
// Stable reference for the no-consumers case so the equality fn short-circuits.
const EMPTY: InterfaceConsumer[] = [];

type StoreNode = { id: string; type?: string; data?: Record<string, unknown> };
type StoreState = { nodeLookup: Map<string, StoreNode> };

// SDK references can live in either config field — jsx_source (JSX mode) or
// content (HTML mode) — so scan both.
function getInterfaceCode(data: Record<string, unknown> | undefined): string {
  const config = (data?.config ?? {}) as Record<string, unknown>;
  const jsx = typeof config.jsx_source === 'string' ? config.jsx_source : '';
  const html = typeof config.content === 'string' ? config.content : '';
  return jsx || html ? `${jsx}\n${html}` : '';
}

function interfaceLabel(data: Record<string, unknown> | undefined): string {
  const raw = data?.label;
  return typeof raw === 'string' && raw.trim() ? raw.trim() : 'Interface';
}

// Scanning every interface's code is O(interfaces × nodes × codeLength). Doing
// that inside each per-node hook on every store tick (drags included) would be
// O(nodes²) work per frame. Instead the full reverse map is built once and
// cached, then rebuilt only when an interface node is added/removed or its data
// object is replaced — xyflow keeps `data` identity stable across drags, so
// only an edit to jsx_source/content/label swaps it.
let cache: { datas: unknown[]; ids: string[]; size: number; map: Map<string, InterfaceConsumer[]> } | null = null;

function getConsumerMap(state: StoreState): Map<string, InterfaceConsumer[]> {
  const interfaces: StoreNode[] = [];
  for (const node of state.nodeLookup.values()) {
    if (node.type === INTERFACE_HTML_REACT) interfaces.push(node);
  }

  const fresh =
    cache !== null &&
    cache.size === state.nodeLookup.size &&
    cache.datas.length === interfaces.length &&
    interfaces.every((n, i) => cache!.datas[i] === n.data && cache!.ids[i] === n.id);
  if (fresh) return cache!.map;

  const map = new Map<string, InterfaceConsumer[]>();
  const allIds = [...state.nodeLookup.keys()];
  for (const iface of interfaces) {
    const code = getInterfaceCode(iface.data);
    if (!code) continue;
    const consumer: InterfaceConsumer = { id: iface.id, label: interfaceLabel(iface.data) };
    for (const id of allIds) {
      if (id === iface.id || !codeReferencesNodeId(code, id)) continue;
      const list = map.get(id);
      if (list) list.push(consumer);
      else map.set(id, [consumer]);
    }
  }
  for (const list of map.values()) list.sort((a, b) => a.id.localeCompare(b.id));

  cache = {
    datas: interfaces.map((n) => n.data),
    ids: interfaces.map((n) => n.id),
    size: state.nodeLookup.size,
    map,
  };
  return map;
}

function consumersEqual(a: InterfaceConsumer[], b: InterfaceConsumer[]): boolean {
  if (a === b) return true;
  if (a.length !== b.length) return false;
  return a.every((c, i) => c.id === b[i].id && c.label === b[i].label);
}

/** Interface-html-react nodes whose code references `nodeId`, sorted by id. */
export function useInterfaceConsumers(nodeId: string): InterfaceConsumer[] {
  return useStore(
    useCallback((state: StoreState) => getConsumerMap(state).get(nodeId) ?? EMPTY, [nodeId]),
    consumersEqual,
  );
}
