import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const VisualstudioIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/visualstudio.svg" alt="" aria-hidden="true" className={className} style={style} />
);

export const VisualstudioNode: NodeDefinition = {
    type: 'automation-visualstudio', label: 'VSOnline', category: 'developer-tools',
    description: 'Manage VSOnline environments, lifecycle, locations and billing',
    Icon: VisualstudioIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo(function VisualstudioNodeComponent(props: NodeProps) {
        return <AutomationNode {...props} Icon={VisualstudioIcon} iconColor="" />;
    }),
};
