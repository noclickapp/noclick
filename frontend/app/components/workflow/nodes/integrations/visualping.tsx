// Visualping monitors pages and reports detected changes through its public API.
// This definition makes the self-registering integration available on the canvas.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const VisualpingIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/visualping.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const VisualpingNode: NodeDefinition = {
    type: 'automation-visualping', label: 'Visualping',
    description: 'Monitor pages, find changes and manage website monitoring jobs',
    keywords: ['website monitoring', 'page changes', 'monitors', 'web monitoring'],
    Icon: VisualpingIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={VisualpingIcon} iconColor="" />),
};
