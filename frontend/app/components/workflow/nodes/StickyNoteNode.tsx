// Sticky Note node definition for workflow canvas.
// Allows users to add visual annotations/notes to their workflows.
// Unlike automation nodes, sticky notes are purely visual and don't execute.

import { memo } from 'react';
import { NodeProps } from '@xyflow/react';
import { StickyNote as StickyNoteIcon } from 'lucide-react';
import StickyNote from './StickyNote';
import { NodeDefinition } from './types';

// Default dimensions for sticky notes - square-ish to look like real sticky notes
const DIMENSIONS = { width: 200, height: 200, iconSize: 48 };

const StickyNoteNodeComponent = (props: NodeProps) => {
    return <StickyNote {...props} />;
};

export const StickyNoteNode: NodeDefinition = {
    type: 'stickyNote',
    label: 'Sticky Note',
    description: 'Add notes',
    Icon: StickyNoteIcon,
    iconColor: 'text-yellow-400',
    dimensions: DIMENSIONS,
    component: memo(StickyNoteNodeComponent),
};
