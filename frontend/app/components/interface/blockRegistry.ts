import {
  ClipboardList,
  Upload,
  AppWindow,
  MessageCircle,
} from 'lucide-react';
import { TableGridIcon, MultimediaIcon } from '~/components/workflow/nodes/interface/interfaceIcons';
// From the schema-free leaf — the block registry rides in the fork canvas
// chunk, which must not pull the full ~9MB schema registry.
import { resolveNodeType } from '~/utils/nodeMeta';
import type { BlockDefinition, BlockCategory } from './types';

export const BLOCK_DEFINITIONS: BlockDefinition[] = [
  // Input
  { type: 'form', label: 'Form', category: 'Input', icon: ClipboardList, description: 'Multi-field form with persistent values and a public shareable link', defaultW: 5, defaultH: 5, minW: 3, minH: 3, nodeType: 'interface-form' },

  // Display
  { type: 'file', label: 'Multimedia', category: 'Display', icon: MultimediaIcon, description: 'Any file — image, audio, video, PDF, or download', defaultW: 5, defaultH: 4, minW: 3, minH: 3, nodeType: 'interface-file' },
  { type: 'dataframe', label: 'Table', category: 'Display', icon: TableGridIcon, description: 'AG Grid table', defaultW: 6, defaultH: 4, minW: 4, minH: 3, nodeType: 'interface-dataframe' },
  { type: 'html-react', label: 'HTML / React', category: 'Display', icon: AppWindow, description: 'HTML or React/JSX with SDK', defaultW: 6, defaultH: 4, minW: 3, minH: 2, nodeType: 'interface-html-react', usesIframe: true },

  // Interactive
  { type: 'file-upload', label: 'File Upload', category: 'Interactive', icon: Upload, description: 'Drop zone with file picker', defaultW: 4, defaultH: 3, minW: 3, minH: 2, nodeType: 'interface-file-upload' },

  // Agent — not in BLOCK_CATEGORIES so it doesn't appear in the palette.
  // Spawned by toggling `show_in_interface=true` on an agent node; always renders fullscreen.
  { type: 'agent-chat', label: 'Agent Chat', category: 'Agent', icon: MessageCircle, description: 'Chat with an agent node', defaultW: 12, defaultH: 8, minW: 6, minH: 4, nodeType: 'agent' },
];

export const BLOCK_CATEGORIES: BlockCategory[] = ['Input', 'Display', 'Interactive'];

export function getBlocksByCategory(category: BlockCategory): BlockDefinition[] {
  return BLOCK_DEFINITIONS.filter(b => b.category === category);
}

export function getBlockDefinition(type: string): BlockDefinition | undefined {
  return BLOCK_DEFINITIONS.find(b => b.type === type);
}

/** Reverse lookup: find the block type for a given workflow node type (e.g. 'interface-markdown' → 'markdown').
 *  Resolves legacy node types (pre-merge saved graphs) to their canonical block. */
export function getBlockTypeForNodeType(nodeType: string): string | undefined {
  const canonical = resolveNodeType(nodeType);
  return BLOCK_DEFINITIONS.find(b => b.nodeType === canonical)?.type;
}
