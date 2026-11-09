// Adds Nifty to the discovered workflow palette and productivity catalog.
// It uses the shared automation editor with the official publisher icon.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const NiftyIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/nifty-pm.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' } as CSSProperties} />
);

export const NiftyPMNode: NodeDefinition = {
    type: 'automation-nifty-pm',
    label: 'Nifty',
    category: 'productivity',
    description: 'Manage projects, tasks, assignments, documents, comments and tracked time',
    keywords: ['project management', 'Nifty PM', 'milestones'],
    Icon: NiftyIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={NiftyIcon} iconColor="" />),
};
