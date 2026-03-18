import {
  ClipboardList,
  Upload,
  FileText,
  Table,
  Image,
  Volume2,
  Video,
  File,
  BarChart3,
  Globe,
  MessageSquare,
  Settings2,
  Code2,
} from 'lucide-react';
import type { BlockDefinition, BlockCategory } from './types';

export const BLOCK_DEFINITIONS: BlockDefinition[] = [
  // Input
  { type: 'form', label: 'Form', category: 'Input', icon: ClipboardList, description: 'Configurable multi-field form', defaultW: 5, defaultH: 5, minW: 3, minH: 3, nodeType: 'interface-form' },
  { type: 'config-form', label: 'Config Form', category: 'Input', icon: Settings2, description: 'Persistent configuration form', defaultW: 5, defaultH: 5, minW: 3, minH: 3, nodeType: 'interface-config-form' },

  // Display
  { type: 'markdown', label: 'Markdown', category: 'Display', icon: FileText, description: 'Rich text display', defaultW: 6, defaultH: 4, minW: 3, minH: 2, nodeType: 'interface-markdown' },
  { type: 'image', label: 'Image', category: 'Display', icon: Image, description: 'Image display', defaultW: 4, defaultH: 4, minW: 2, minH: 2, nodeType: 'interface-image' },
  { type: 'audio', label: 'Audio', category: 'Display', icon: Volume2, description: 'Waveform audio player', defaultW: 6, defaultH: 2, minW: 4, minH: 2, nodeType: 'interface-audio' },
  { type: 'video', label: 'Video', category: 'Display', icon: Video, description: 'Video player', defaultW: 6, defaultH: 5, minW: 4, minH: 3, nodeType: 'interface-video' },
  { type: 'file', label: 'File / PDF', category: 'Display', icon: File, description: 'PDF embed or file preview', defaultW: 6, defaultH: 5, minW: 3, minH: 3, nodeType: 'interface-file' },
  { type: 'dataframe', label: 'Table', category: 'Display', icon: Table, description: 'AG Grid table', defaultW: 6, defaultH: 4, minW: 4, minH: 3, nodeType: 'interface-dataframe' },
  { type: 'plot', label: 'Plot', category: 'Display', icon: BarChart3, description: 'Chart / graph', defaultW: 6, defaultH: 4, minW: 4, minH: 3, nodeType: 'interface-plot' },
  { type: 'html', label: 'HTML', category: 'Display', icon: Globe, description: 'Sandboxed HTML rendering', defaultW: 6, defaultH: 4, minW: 3, minH: 2, nodeType: 'interface-html' },
  { type: 'custom-component', label: 'Custom Component', category: 'Display', icon: Code2, description: 'React/JSX component', defaultW: 6, defaultH: 6, minW: 4, minH: 4, nodeType: 'interface-custom-component' },

  // Interactive
  { type: 'file-upload', label: 'File Upload', category: 'Interactive', icon: Upload, description: 'Drop zone with file picker', defaultW: 4, defaultH: 3, minW: 3, minH: 2, nodeType: 'interface-file-upload' },
  { type: 'chatbot', label: 'Chatbot', category: 'Interactive', icon: MessageSquare, description: 'Chat interface', defaultW: 6, defaultH: 6, minW: 4, minH: 4, nodeType: 'interface-chatbot' },
];

export const BLOCK_CATEGORIES: BlockCategory[] = ['Input', 'Display', 'Interactive'];

export function getBlocksByCategory(category: BlockCategory): BlockDefinition[] {
  return BLOCK_DEFINITIONS.filter(b => b.category === category);
}

export function getBlockDefinition(type: string): BlockDefinition | undefined {
  return BLOCK_DEFINITIONS.find(b => b.type === type);
}

/** Reverse lookup: find the block type for a given workflow node type (e.g. 'interface-markdown' → 'markdown') */
export function getBlockTypeForNodeType(nodeType: string): string | undefined {
  return BLOCK_DEFINITIONS.find(b => b.nodeType === nodeType)?.type;
}
