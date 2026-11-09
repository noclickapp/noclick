// Conveyor's native portal actions share the standard automation node renderer.
// The publisher's favicon identifies the service; its source is recorded beside it.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const ConveyorIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/conveyor.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' } as CSSProperties} />
);

export const ConveyorNode: NodeDefinition = {
    type: 'automation-conveyor', category: 'documents', label: 'Conveyor',
    description: 'Manage Trust Center requests, authorizations, documents and folders',
    keywords: ['trust center', 'security review', 'customer trust'],
    Icon: ConveyorIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={ConveyorIcon} iconColor="" />),
};
