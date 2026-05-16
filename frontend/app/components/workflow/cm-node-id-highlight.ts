// CodeMirror 6 extension that highlights workflow node IDs found in code.
// Reads node IDs from the global workflow state and decorates matching strings.

import { ViewPlugin, Decoration, type DecorationSet, type ViewUpdate, type EditorView } from '@codemirror/view';
import { RangeSetBuilder } from '@codemirror/state';
import { findNodeIdMatches } from '~/lib/nodeIdReferences';

type CanvasNode = { id?: string; type?: string };

function getWorkflowNodeIds(): string[] {
  const win = window as unknown as {
    __workflowTest?: { getNodes?: () => CanvasNode[] };
    __reactFlowInstance?: { getNodes?: () => CanvasNode[] };
  };
  const nodes = win.__workflowTest?.getNodes?.() ?? win.__reactFlowInstance?.getNodes?.() ?? [];
  return nodes
    .filter((n): n is { id: string; type: string } => !!n.id && !!n.type && !n.type.startsWith('collaborator'))
    .map((n) => n.id);
}

const nodeIdMark = Decoration.mark({ class: 'cm-node-id-highlight' });

function buildDecorations(view: EditorView, nodeIds: string[]): DecorationSet {
  if (nodeIds.length === 0) return Decoration.none;

  const doc = view.state.doc.toString();
  const matches = findNodeIdMatches(doc, nodeIds);

  if (matches.length === 0) return Decoration.none;

  // RangeSetBuilder requires sorted, non-overlapping ranges
  matches.sort((a, b) => a.from - b.from || a.to - b.to);

  const builder = new RangeSetBuilder<Decoration>();
  let last = -1;
  for (const { from, to } of matches) {
    if (from >= last) {
      builder.add(from, to, nodeIdMark);
      last = to;
    }
  }
  return builder.finish();
}

export const nodeIdHighlighter = ViewPlugin.fromClass(
  class {
    decorations: DecorationSet;
    private nodeIds: string[];

    constructor(view: EditorView) {
      this.nodeIds = getWorkflowNodeIds();
      this.decorations = buildDecorations(view, this.nodeIds);
    }

    update(update: ViewUpdate) {
      if (update.docChanged || update.viewportChanged) {
        this.nodeIds = getWorkflowNodeIds();
        this.decorations = buildDecorations(update.view, this.nodeIds);
      }
    }
  },
  { decorations: (v) => v.decorations },
);
