"""
Deterministic Sugiyama-style autolayout algorithm for NoClick workflow nodes.
Computes left-to-right layered positions for nodes based on graph topology.
"""

from collections import defaultdict, deque

# ─── Node Dimensions ───────────────────────────────────────────────────────────

DEFAULT_DIMS = (90, 90)

NODE_TYPE_DIMS = {
    'trigger-cron': (90, 90),
    'trigger-run': (90, 90),
    'trigger-webhook': (90, 90),
    'form-input': (90, 90),
    'agent': (200, 140),
    'tool': (90, 90),
    'mcp-server': (90, 90),
    'iteration': (90, 90),
    'conditional': (90, 90),
    'switch': (90, 90),
    'filter': (110, 110),
    'merge': (110, 110),
    'delay': (90, 90),
    'state-manager': (90, 90),
    'set-variable': (90, 90),
    'interface-form': (350, 280),
    'interface-file': (350, 240),
    'interface-dataframe': (350, 200),
    'interface-html-react': (800, 600),
    'interface-file-upload': (350, 160),
}


def get_dims(node):
    w = node.get('width')
    h = node.get('height')
    if w and h:
        return (w, h)
    from nodes.core.registry import resolve_node_type
    return NODE_TYPE_DIMS.get(resolve_node_type(node['type']), DEFAULT_DIMS)


# ─── Layout Constants ──────────────────────────────────────────────────────────

# H_GAP sized so the default 90px-wide automation nodes still have ~50px of
# clearance when they expand to ~220px during the agentic builder's editing
# panel (AutomationNode.EXPANDED_WIDTH). Without the extra room, nodes collide
# horizontally while the brain is writing to them.
H_GAP = 180
V_GAP = 80
SUBGRAPH_GAP = 300
LOOP_Y_OFFSET = 100
BRANCH_Y_OFFSET = 120
RIGHT_Y_OFFSET = -100
# Gap from agent bottom to the attached tool row — sized so the agent's
# label, run-status pill, and the edges' "N tools" chips fit between them.
TOOL_ATTACH_V_GAP = 180
# Extra gap when the agent also renders a "Used by interface" badge in its
# bottom stack (an interface-html-react node references it by id).
TOOL_ATTACH_BADGE_EXTRA = 40
# Horizontal gap between attached tools — sized so each tool's label below
# it doesn't collide with its neighbor's.
TOOL_ATTACH_H_GAP = 90

# Stability constants for pinned-node autolayout (DynaDAG-style).
# When pinned_node_ids is provided, pinned nodes resist movement.
PINNED_ORDER_ALPHA = 0.1   # 10% barycenter, 90% current order for pinned nodes
PINNED_Y_BETA = 0.1        # 10% computed Y, 90% current Y for pinned nodes
PINNED_POS_BLEND = 0.1     # Final position blend: 10% computed, 90% original for pinned nodes


def handle_y_offset(e, reverse=False, diamond_edges=None, handle_positions=None):
    """Get Y offset for an edge based on sourceHandle. reverse=True for backward pass."""
    sh = e.get('sourceHandle', '')
    sign = -1 if reverse else 1
    if sh == 'loop':
        return sign * LOOP_Y_OFFSET
    if sh == 'false':
        return sign * BRANCH_Y_OFFSET
    if sh == 'true':
        return sign * -BRANCH_Y_OFFSET
    if sh == 'right':
        return sign * RIGHT_Y_OFFSET
    if diamond_edges and e['id'] in diamond_edges:
        return sign * BRANCH_Y_OFFSET
    if handle_positions and e['id'] in handle_positions:
        return sign * handle_positions[e['id']] * BRANCH_Y_OFFSET
    return 0


# ─── Back-Edge Detection ──────────────────────────────────────────────────────

def detect_back_edges(node_ids, fwd_adj, node_map):
    """
    Detect back-edges using iteration-aware structural analysis.
    For each iteration node, edges from its loop descendants back to
    the iteration are back-edges. Then use DFS for any remaining cycles.
    """
    back_edge_ids = set()
    node_ids = set(node_ids)

    # Phase 1: Structural detection for iteration loops
    iteration_nodes = {nid for nid in node_ids if node_map[nid]['type'] == 'iteration'}

    for iter_nid in iteration_nodes:
        loop_descendants = set()
        q = deque()
        for (v, e) in fwd_adj.get(iter_nid, []):
            if e.get('sourceHandle') == 'loop' and v in node_ids:
                q.append(v)

        while q:
            u = q.popleft()
            if u in loop_descendants or u == iter_nid:
                continue
            loop_descendants.add(u)
            for (w, e2) in fwd_adj.get(u, []):
                if w != iter_nid and w in node_ids and w not in loop_descendants:
                    q.append(w)

        for desc in loop_descendants:
            for (v, e) in fwd_adj.get(desc, []):
                if v == iter_nid:
                    back_edge_ids.add(e['id'])

    # Phase 2: DFS for any remaining cycles
    remaining_fwd = defaultdict(list)
    for nid in node_ids:
        for (v, e) in fwd_adj.get(nid, []):
            if e['id'] not in back_edge_ids and v in node_ids:
                remaining_fwd[nid].append((v, e))

    WHITE, GRAY, BLACK = 0, 1, 2
    color = {nid: WHITE for nid in node_ids}

    in_deg = defaultdict(int)
    for nid in node_ids:
        for (v, e) in remaining_fwd[nid]:
            in_deg[v] += 1
    sources = sorted([nid for nid in node_ids if in_deg.get(nid, 0) == 0])
    non_sources = sorted([nid for nid in node_ids if in_deg.get(nid, 0) > 0])

    def dfs(u):
        color[u] = GRAY
        for (v, e) in remaining_fwd[u]:
            if color[v] == GRAY:
                back_edge_ids.add(e['id'])
            elif color[v] == WHITE:
                dfs(v)
        color[u] = BLACK

    for nid in sources + non_sources:
        if color[nid] == WHITE:
            dfs(nid)

    return back_edge_ids


# ─── Graph Utilities ───────────────────────────────────────────────────────────

def find_connected_components(node_ids, edges):
    adj = defaultdict(set)
    for e in edges:
        s, t = e['source'], e['target']
        if s in node_ids and t in node_ids:
            adj[s].add(t)
            adj[t].add(s)

    visited = set()
    components = []

    for nid in sorted(node_ids):
        if nid not in visited:
            comp = set()
            q = deque([nid])
            while q:
                u = q.popleft()
                if u in visited:
                    continue
                visited.add(u)
                comp.add(u)
                for v in adj[u]:
                    if v not in visited:
                        q.append(v)
            components.append(comp)

    components.sort(key=len, reverse=True)
    return components


# ─── Core Layout ───────────────────────────────────────────────────────────────

def layout_subgraph(node_ids, node_map, edges, dims, pinned_node_ids=None):
    node_ids = set(node_ids)

    # Build adjacency
    fwd = defaultdict(list)
    bwd = defaultdict(list)
    for e in edges:
        s, t = e['source'], e['target']
        if s in node_ids and t in node_ids:
            fwd[s].append((t, e))
            bwd[t].append((s, e))

    # Detect back-edges
    back_edge_ids = detect_back_edges(node_ids, fwd, node_map)

    # Collect back-edge source nodes (last node in loop body that links back)
    back_edge_sources = set()
    for e in edges:
        if e['id'] in back_edge_ids and e['source'] in node_ids:
            back_edge_sources.add(e['source'])

    # Build DAG
    dag_fwd = defaultdict(list)
    dag_bwd = defaultdict(list)
    dag_in_deg = {nid: 0 for nid in node_ids}
    for e in edges:
        if e['id'] in back_edge_ids:
            continue
        s, t = e['source'], e['target']
        if s in node_ids and t in node_ids:
            dag_fwd[s].append((t, e))
            dag_bwd[t].append((s, e))
            dag_in_deg[t] += 1

    # ── Build handle position map for multi-output nodes (switch, etc.) ──
    handle_positions = {}
    for nid in node_ids:
        node = node_map[nid]
        ntype = node.get('type', '')
        config = node.get('config', {})
        handle_order = None
        if ntype == 'switch':
            cases = config.get('switch_cases', [])
            if isinstance(cases, list) and cases:
                handle_order = [c.get('value', '') for c in cases if isinstance(c, dict)]
        if not handle_order or len(handle_order) < 2:
            continue
        n = len(handle_order)
        for (_, edge) in dag_fwd.get(nid, []):
            sh = edge.get('sourceHandle', '')
            if sh in handle_order:
                idx = handle_order.index(sh)
                handle_positions[edge['id']] = (idx - (n - 1) / 2) / max(1, (n - 1) / 2)

    # Topological sort
    topo = []
    q = deque(sorted([nid for nid in node_ids if dag_in_deg[nid] == 0]))
    deg = dict(dag_in_deg)
    while q:
        u = q.popleft()
        topo.append(u)
        for (v, _) in dag_fwd[u]:
            deg[v] -= 1
            if deg[v] == 0:
                q.append(v)
    for nid in node_ids:
        if nid not in topo:
            topo.append(nid)

    # ── Layer assignment (longest path from sources) ──
    layer = {nid: 0 for nid in node_ids}
    for u in topo:
        for (v, _) in dag_fwd[u]:
            layer[v] = max(layer[v], layer[u] + 1)

    depth = dict(layer)

    # ── Compaction: push source nodes closer to targets ──
    for nid in node_ids:
        if dag_in_deg[nid] == 0 and dag_fwd[nid]:
            min_succ_layer = min(layer[v] for (v, _) in dag_fwd[nid])
            desired = min_succ_layer - 1
            if desired > layer[nid]:
                layer[nid] = desired

    # ── Compact side branches into predecessor's layer ──
    compacted = set()
    diamond_side_edge_ids = set()
    diamond_side_nodes = set()
    for nid in topo:
        preds = dag_bwd[nid]
        if len(preds) != 1:
            continue
        pred_id, pred_edge = preds[0]
        if pred_edge.get('sourceHandle') == 'loop':
            continue
        if layer[nid] != layer[pred_id] + 1:
            continue
        other_succs = [(v, e) for (v, e) in dag_fwd[pred_id] if v != nid]
        if not any(layer[v] > layer[nid] for (v, _) in other_succs):
            continue
        my_succs = dag_fwd[nid]
        if my_succs and min(layer[v] for (v, _) in my_succs) < layer[pred_id] + 2:
            continue
        other_succ_ids = {v for (v, _) in other_succs}
        if other_succ_ids:
            is_diamond = False
            visited = set()
            bfs_q = deque([nid])
            while bfs_q:
                u = bfs_q.popleft()
                if u in visited:
                    continue
                visited.add(u)
                for (w, _) in dag_fwd[u]:
                    if w in other_succ_ids:
                        is_diamond = True
                        break
                    if w not in visited:
                        bfs_q.append(w)
                if is_diamond:
                    break
            if is_diamond:
                diamond_side_edge_ids.add(pred_edge['id'])
                diamond_side_nodes.update(visited)
                continue
        layer[nid] = layer[pred_id]
        compacted.add(nid)

    # ── Recompute layers after compaction ──
    for u in topo:
        if u in compacted:
            pred_id = dag_bwd[u][0][0]
            layer[u] = layer[pred_id]
            continue
        if dag_in_deg[u] == 0:
            continue
        preds = dag_bwd[u]
        if preds:
            layer[u] = max(layer[pid] + 1 for (pid, _) in preds)

    # ── Group by layer ──
    layers = defaultdict(list)
    for nid in node_ids:
        layers[layer[nid]].append(nid)
    max_layer = max(layers.keys()) if layers else 0

    # ── Ordering within layers ──
    pos_in_layer = {}

    def type_priority(nid):
        t = node_map[nid]['type']
        if t.startswith('trigger'):
            return 0
        if t.startswith('interface'):
            return 1
        return 2

    def type_sort_key(nid):
        return node_map[nid]['type']

    def handle_offset(e):
        sh = e.get('sourceHandle', '')
        if sh == 'loop':
            return 0.5
        if sh == 'false':
            return 0.4
        if sh == 'true':
            return -0.4
        if sh == 'right':
            return -0.3
        if e['id'] in handle_positions:
            return handle_positions[e['id']] * 0.5
        return 0

    def _sort_layer(layer_nodes, bary, current_order=None):
        if not layer_nodes:
            return
        # Stability: blend barycenter with current order for pinned nodes
        if current_order and pinned_node_ids:
            for nid in layer_nodes:
                if nid in pinned_node_ids and nid in current_order:
                    raw = bary.get(nid, 0)
                    bary[nid] = PINNED_ORDER_ALPHA * raw + (1 - PINNED_ORDER_ALPHA) * current_order[nid]

        pred_sets = {}
        for nid in layer_nodes:
            preds = frozenset(pid for (pid, _) in dag_bwd[nid] if pid in pos_in_layer)
            pred_sets[nid] = preds
        unique_pred_sets = set(pred_sets.values())

        if len(unique_pred_sets) == 1 and len(layer_nodes) > 2:
            layer_nodes.sort(key=lambda nid: (type_sort_key(nid), bary.get(nid, 0), nid))
        else:
            layer_nodes.sort(key=lambda nid: (bary.get(nid, 0), type_sort_key(nid), nid))

    # Stability: seed pos_in_layer from current Y positions for pinned nodes
    if pinned_node_ids:
        pinned_in_comp = pinned_node_ids & node_ids
        for L in range(max_layer + 1):
            pinned_in_layer = [nid for nid in layers[L] if nid in pinned_in_comp]
            if pinned_in_layer:
                pinned_in_layer.sort(
                    key=lambda nid: node_map[nid].get('position', {}).get('y', 0)
                )
                for i, nid in enumerate(pinned_in_layer):
                    pos_in_layer[nid] = i

    # Multiple forward + backward sweeps
    for sweep in range(3):
        for L in range(max_layer + 1):
            if L == 0 and sweep == 0:
                layers[L].sort(key=lambda nid: (type_priority(nid), nid))
            else:
                bary = {}
                for nid in layers[L]:
                    vals = []
                    for (pid, e) in dag_bwd[nid]:
                        if pid in pos_in_layer:
                            vals.append(pos_in_layer[pid] + handle_offset(e))
                    bary[nid] = sum(vals) / len(vals) if vals else pos_in_layer.get(nid, 0)
                _sort_layer(layers[L], bary,
                           current_order=dict(pos_in_layer) if pinned_node_ids else None)
            for i, nid in enumerate(layers[L]):
                pos_in_layer[nid] = i

        for L in range(max_layer - 1, -1, -1):
            bary = {}
            for nid in layers[L]:
                vals = [pos_in_layer.get(v, 0) for (v, _) in dag_fwd[nid]]
                bary[nid] = sum(vals) / len(vals) if vals else pos_in_layer.get(nid, 0)
            _sort_layer(layers[L], bary,
                       current_order=dict(pos_in_layer) if pinned_node_ids else None)
            for i, nid in enumerate(layers[L]):
                pos_in_layer[nid] = i

    # ── X-coordinate assignment ──
    layer_x = {}
    x = 0
    for L in range(max_layer + 1):
        if L not in layers or not layers[L]:
            layer_x[L] = x
            x += 90 + H_GAP
            continue
        layer_x[L] = x
        max_w = max(dims[nid][0] for nid in layers[L])
        x += max_w + H_GAP

    # ── Y-coordinate assignment ──
    node_y = {}

    # Identify mixed layers where tall source nodes would displace chain nodes
    mixed_layers = set()
    tall_sources = set()
    for L in range(max_layer + 1):
        ln = layers[L]
        sources = [n for n in ln if dag_in_deg[n] == 0]
        chains = [n for n in ln if dag_in_deg[n] > 0]
        if not sources or not chains:
            continue
        max_chain_h = max(dims[n][1] for n in chains)
        tall_in_layer = [n for n in sources if dims[n][1] > max_chain_h + V_GAP]
        if tall_in_layer:
            mixed_layers.add(L)
            tall_sources.update(tall_in_layer)

    def resolve_layer(L):
        if L in mixed_layers:
            non_tall = [n for n in layers[L] if n not in tall_sources]
            _resolve_overlaps(non_tall, node_y, dims, V_GAP)
        else:
            _resolve_overlaps(layers[L], node_y, dims, V_GAP)

    # Forward pass
    for L in range(max_layer + 1):
        deferred = []
        for nid in layers[L]:
            all_vals = []
            main_vals = []
            for (pid, e) in dag_bwd[nid]:
                if pid in node_y and layer[pid] < L:
                    y = node_y[pid] + handle_y_offset(e, diamond_edges=diamond_side_edge_ids, handle_positions=handle_positions)
                    w = max(1, depth[pid])
                    all_vals.append((y, w))
                    if pid not in diamond_side_nodes:
                        main_vals.append((y, w))
            vals = main_vals if main_vals else all_vals
            if vals:
                total_w = sum(w for _, w in vals)
                node_y[nid] = sum(y * w for y, w in vals) / total_w
                # Stability: blend computed Y with current Y for pinned nodes
                if pinned_node_ids and nid in pinned_node_ids:
                    cur_pos = node_map[nid].get('position', {})
                    cur_y_center = cur_pos.get('y', 0) + dims[nid][1] / 2
                    node_y[nid] = PINNED_Y_BETA * node_y[nid] + (1 - PINNED_Y_BETA) * cur_y_center
            else:
                deferred.append(nid)
        for nid in deferred:
            for (pid, e) in dag_bwd[nid]:
                if pid in node_y and layer[pid] == L:
                    node_y[nid] = node_y[pid]
                    break
            else:
                # Stability: pinned source nodes use their current Y instead of 0
                if pinned_node_ids and nid in pinned_node_ids:
                    cur_pos = node_map[nid].get('position', {})
                    node_y[nid] = cur_pos.get('y', 0) + dims[nid][1] / 2
                else:
                    node_y[nid] = 0
        resolve_layer(L)

    # Iterative refinement
    for refine_iter in range(3):
        # Backward pass
        for L in range(max_layer - 1, -1, -1):
            for nid in layers[L]:
                cross_succs = [(v, e) for (v, e) in dag_fwd[nid] if layer[v] > L]
                if len(cross_succs) <= 1:
                    continue
                cross_preds = [(p, e) for (p, e) in dag_bwd[nid] if layer[p] < L]
                all_vals = []
                main_vals = []
                for (v, e) in cross_succs:
                    if v in node_y:
                        y = node_y[v] + handle_y_offset(e, reverse=True, diamond_edges=diamond_side_edge_ids, handle_positions=handle_positions)
                        all_vals.append(y)
                        if v not in diamond_side_nodes:
                            main_vals.append(y)
                vals = main_vals if main_vals else all_vals
                if vals:
                    ideal = sum(vals) / len(vals)
                    n_pred = len(cross_preds)
                    keep = min(0.8, 0.4 + 0.05 * n_pred)
                    node_y[nid] = keep * node_y[nid] + (1 - keep) * ideal
                    # Stability: pull pinned nodes back toward current Y
                    if pinned_node_ids and nid in pinned_node_ids:
                        cur_pos = node_map[nid].get('position', {})
                        cur_y_center = cur_pos.get('y', 0) + dims[nid][1] / 2
                        node_y[nid] = PINNED_Y_BETA * node_y[nid] + (1 - PINNED_Y_BETA) * cur_y_center
            resolve_layer(L)

        # Forward pass
        for L in range(1, max_layer + 1):
            for nid in layers[L]:
                cross_preds = [(p, e) for (p, e) in dag_bwd[nid] if layer[p] < L]
                if not cross_preds:
                    continue
                cross_succs = [(v, e) for (v, e) in dag_fwd[nid] if layer[v] > L]
                all_vals = []
                main_vals = []
                for (pid, e) in cross_preds:
                    if pid in node_y:
                        y = node_y[pid] + handle_y_offset(e, diamond_edges=diamond_side_edge_ids, handle_positions=handle_positions)
                        w = max(1, depth[pid])
                        all_vals.append((y, w))
                        if pid not in diamond_side_nodes:
                            main_vals.append((y, w))
                vals = main_vals if main_vals else all_vals
                if vals:
                    total_w = sum(ww for _, ww in vals)
                    ideal = sum(yy * ww for yy, ww in vals) / total_w
                    n_succ = len(cross_succs)
                    keep = min(0.8, 0.4 + 0.05 * n_succ)
                    node_y[nid] = keep * node_y[nid] + (1 - keep) * ideal
                    # Stability: pull pinned nodes back toward current Y
                    if pinned_node_ids and nid in pinned_node_ids:
                        cur_pos = node_map[nid].get('position', {})
                        cur_y_center = cur_pos.get('y', 0) + dims[nid][1] / 2
                        node_y[nid] = PINNED_Y_BETA * node_y[nid] + (1 - PINNED_Y_BETA) * cur_y_center
            resolve_layer(L)

    # ── Push back-edge source nodes down so backward edges clear the loop body ──
    for nid in back_edge_sources:
        if nid in node_y:
            node_y[nid] += LOOP_Y_OFFSET
    affected_layers = {layer[nid] for nid in back_edge_sources}
    for L in affected_layers:
        resolve_layer(L)

    # ── Reposition tall source nodes in mixed layers above the chain ──
    for L in mixed_layers:
        layer_nodes = layers[L]
        tall_in_layer = [n for n in layer_nodes if n in tall_sources]
        non_tall = [n for n in layer_nodes if n not in tall_sources]
        if not tall_in_layer or not non_tall:
            continue
        _resolve_overlaps(non_tall, node_y, dims, V_GAP)
        top_y = min(node_y[n] - dims[n][1] / 2 for n in non_tall)
        for src in sorted(tall_in_layer, key=lambda n: node_y[n], reverse=True):
            node_y[src] = top_y - V_GAP - dims[src][1] / 2
            top_y = node_y[src] - dims[src][1] / 2

    # ── Convert to top-left positions ──
    positions = {}
    for nid in node_ids:
        L = layer[nid]
        w, h = dims[nid]
        max_w = max(dims[n][0] for n in layers[L])
        x_offset = (max_w - w) / 2
        positions[nid] = {
            'x': layer_x[L] + x_offset,
            'y': node_y[nid] - h / 2,
        }

    return positions


def _resolve_overlaps(layer_nodes, y_centers, dims, gap):
    if len(layer_nodes) <= 1:
        return
    sorted_nodes = sorted(layer_nodes, key=lambda nid: y_centers[nid])

    original_center = sum(y_centers[nid] for nid in sorted_nodes) / len(sorted_nodes)

    for i in range(1, len(sorted_nodes)):
        prev = sorted_nodes[i - 1]
        curr = sorted_nodes[i]
        prev_bottom = y_centers[prev] + dims[prev][1] / 2
        curr_top = y_centers[curr] - dims[curr][1] / 2
        if curr_top - prev_bottom < gap:
            y_centers[curr] = prev_bottom + gap + dims[curr][1] / 2

    new_center = sum(y_centers[nid] for nid in sorted_nodes) / len(sorted_nodes)
    shift = original_center - new_center
    if abs(shift) > 1:
        for nid in sorted_nodes:
            y_centers[nid] += shift


# ─── Main autolayout ──────────────────────────────────────────────────────────

def autolayout(nodes_raw, edges_raw, pinned_node_ids=None):
    """Compute autolayout positions for workflow nodes.

    Args:
        nodes_raw: List of node dicts with 'id', 'type', and optionally 'config', 'width', 'height'
        edges_raw: List of edge dicts with 'id', 'source', 'target', and optionally 'sourceHandle'
        pinned_node_ids: Optional set of node IDs that should resist movement (stability mode).
            When provided, pinned nodes get stability penalties in ordering and Y-coordinate
            phases, while unpinned nodes (newly added) are placed freely. When None, the
            algorithm behaves as a full relayout with no stability constraints.

    Returns:
        Dict mapping node_id -> {'x': float, 'y': float} (top-left positions)
    """
    nodes = [n for n in nodes_raw if n.get('type') != 'stickyNote']
    if not nodes:
        return {}

    node_map = {n['id']: n for n in nodes}
    node_ids = set(node_map.keys())
    dims = {n['id']: get_dims(n) for n in nodes}

    # ── Separate tool→agent vertical attachments ──
    # Tool providers (tool/mcp-server/alarm/filesystem nodes AND integration
    # nodes in provider mode) connect into an agent's bottom handle and are
    # positioned below their agent rather than in the horizontal layout.
    # targetHandle == 'bottom' is the defining attribute of these edges
    # (nodes/agent/node_op_tools.is_node_op_provider); sourceHandle == 'top' is
    # the fallback for edges that lost their targetHandle in a serialization hop.
    # Both identify a tool provider regardless of source node type — integration
    # providers (automation-*) included, not just tool/mcp-server nodes.
    tool_agent_edge_ids = set()
    agent_tools = defaultdict(list)
    for e in edges_raw:
        src, tgt = e.get('source'), e.get('target')
        # Consumers of provider attachments: agents AND hosting-mode MCP nodes
        # (providers hang below the MCP node, which itself may hang below an
        # agent — a 3-tier stack).
        if not (src in node_map and tgt in node_map
                and node_map[tgt]['type'] in ('agent', 'mcp-server')):
            continue
        # tgt is already an agent / mcp-server (guard above), so the top source
        # handle or the bottom target handle is unambiguously a provider wiring.
        is_provider_edge = (
            e.get('targetHandle') == 'bottom'
            or e.get('sourceHandle') == 'top'
        )
        if is_provider_edge:
            tool_agent_edge_ids.add(e['id'])
            agent_tools[tgt].append(src)

    attached_only_tools = set()
    if agent_tools:
        candidate_tools = {tid for tids in agent_tools.values() for tid in tids}
        for tool_id in candidate_tools:
            has_other = any(
                e['id'] not in tool_agent_edge_ids
                and (e.get('source') == tool_id or e.get('target') == tool_id)
                for e in edges_raw
            )
            if not has_other:
                attached_only_tools.add(tool_id)

    # Per-agent vertical drop of its attached tool row. Agents referenced by an
    # interface-html-react node's code render an extra "Used by interface"
    # badge in their bottom stack (mirrors the frontend's useInterfaceConsumers:
    # a plain id-containment check on jsx_source/content), so the row drops
    # further. Used by the attach positioning AND the unanchored-component
    # stacking below (so fresh disconnected nodes don't land inside the row).
    interface_codes = []
    for n in nodes:
        if n.get('type') != 'interface-html-react':
            continue
        cfg = n.get('config') or n.get('data') or {}
        if isinstance(cfg.get('config'), dict):
            cfg = {**cfg['config'], **{k: v for k, v in cfg.items() if k != 'config'}}
        code = f"{cfg.get('jsx_source') or ''}\n{cfg.get('content') or ''}"
        if code.strip():
            interface_codes.append(code)

    agent_row_drop = {}
    for agent_id, tool_ids in agent_tools.items():
        attached = [t for t in tool_ids if t in attached_only_tools]
        if attached:
            badge = any(agent_id in code for code in interface_codes)
            agent_row_drop[agent_id] = (
                TOOL_ATTACH_V_GAP + (TOOL_ATTACH_BADGE_EXTRA if badge else 0),
                max(dims[t][1] for t in attached),
            )

    layout_node_ids = node_ids - attached_only_tools
    layout_edges = [e for e in edges_raw if e['id'] not in tool_agent_edge_ids]

    components = find_connected_components(layout_node_ids, layout_edges)

    all_positions = {}

    def _has_real_anchor(nids):
        """True if any node has an explicit original position (even at origin)."""
        for nid in nids:
            if node_map[nid].get('position') is not None:
                return True
        return False

    # For components whose anchor nodes have no real position (fresh/disconnected
    # nodes added without any prior layout), stack them vertically below the
    # highest-placed component so they don't all collapse to (0,0).
    next_unanchored_y = 0.0

    for comp in components:
        positions = layout_subgraph(comp, node_map, layout_edges, dims, pinned_node_ids)
        if not positions:
            continue

        # Shift the laid-out subgraph so its center matches the original center.
        # When pinned_node_ids is set, anchor to pinned nodes' centroid only so
        # new nodes don't drag the centroid away from where existing nodes were.
        if pinned_node_ids:
            pinned_in_comp = [nid for nid in comp if nid in pinned_node_ids and nid in positions]
            anchor_ids = pinned_in_comp if pinned_in_comp else list(comp)
        else:
            anchor_ids = list(comp)

        if _has_real_anchor(anchor_ids):
            orig_cx = sum(node_map[nid].get('position', {}).get('x', 0) for nid in anchor_ids) / len(anchor_ids)
            orig_cy = sum(node_map[nid].get('position', {}).get('y', 0) for nid in anchor_ids) / len(anchor_ids)
            layout_cx = sum(positions[nid]['x'] for nid in anchor_ids if nid in positions) / len(anchor_ids)
            layout_cy = sum(positions[nid]['y'] for nid in anchor_ids if nid in positions) / len(anchor_ids)
            dx = orig_cx - layout_cx
            dy = orig_cy - layout_cy
        else:
            # No anchor positions — place this component below the previous
            # unanchored one so fresh disconnected nodes stack rather than
            # pile onto origin.
            layout_ys = [positions[nid]['y'] for nid in positions]
            min_y = min(layout_ys) if layout_ys else 0.0
            max_y = max(layout_ys) if layout_ys else 0.0
            # Agents in this component may carry an attached tool row below
            # them (positioned after this loop) — extend the span so the next
            # stacked component doesn't land inside the row.
            attach_extent = max(
                (drop + tool_h for aid, (drop, tool_h) in agent_row_drop.items() if aid in positions),
                default=0.0,
            )
            dx = 0.0
            dy = next_unanchored_y - min_y
            next_unanchored_y += (max_y - min_y) + attach_extent + SUBGRAPH_GAP

        for nid in positions:
            positions[nid]['x'] += dx
            positions[nid]['y'] += dy

        # Final position blend: pull pinned nodes toward their original positions.
        # This catches X displacement (from layer/compaction changes) that the
        # internal Y-stability blending cannot address.
        if pinned_node_ids:
            for nid in positions:
                if nid in pinned_node_ids:
                    orig_pos = node_map[nid].get('position', {})
                    orig_x = orig_pos.get('x', positions[nid]['x'])
                    orig_y = orig_pos.get('y', positions[nid]['y'])
                    positions[nid]['x'] = PINNED_POS_BLEND * positions[nid]['x'] + (1 - PINNED_POS_BLEND) * orig_x
                    positions[nid]['y'] = PINNED_POS_BLEND * positions[nid]['y'] + (1 - PINNED_POS_BLEND) * orig_y

        all_positions.update(positions)

    # ── Position attached tools centered below their consumers ──
    # Nested placement: a hosting-mode MCP node is itself attached below an agent,
    # and ITS providers attach below it — the inner row can only be placed
    # once the MCP node has a position, so loop until no row makes progress.
    pending_rows = dict(agent_tools)
    while pending_rows:
        progressed = False
        for agent_id, tool_ids in list(pending_rows.items()):
            tools = sorted(tid for tid in tool_ids if tid in attached_only_tools)
            if not tools:
                del pending_rows[agent_id]
                progressed = True
                continue
            if agent_id not in all_positions:
                continue
            del pending_rows[agent_id]
            progressed = True

            agent_pos = all_positions[agent_id]
            agent_w, agent_h = dims[agent_id]
            agent_cx = agent_pos['x'] + agent_w / 2

            # Flat row centered under the consumer. Attached tools have no
            # other edges by construction (see attached_only_tools), so
            # nothing hangs off them that could overlap a neighbor.
            max_tw = max(dims[t][0] for t in tools)
            h_step = max_tw + TOOL_ATTACH_H_GAP

            total_w = (len(tools) - 1) * h_step + max_tw
            start_x = agent_cx - total_w / 2
            row_y = agent_pos['y'] + agent_h + agent_row_drop[agent_id][0]

            for i, tid in enumerate(tools):
                all_positions[tid] = {
                    'x': start_x + i * h_step,
                    'y': row_y,
                }
        if not progressed:
            break  # consumer never placed (kept original position)

    return all_positions
