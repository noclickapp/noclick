import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const ISNIcon = ({
    className,
    style,
}: {
    className?: string;
    style?: CSSProperties;
}) => (
    <img
        src="/icons/isn.png"
        alt=""
        aria-hidden="true"
        className={className}
        style={
            {
                ...style,
                '--brand-invert': 0,
                objectFit: 'contain',
            } as CSSProperties
        }
    />
);

export const ISNNode: NodeDefinition = {
    type: 'automation-isn',
    category: 'industry',
    label: 'ISN',
    keywords: ['Inspection Support Network', 'home inspections'],
    description:
        'Manage inspections, clients, agents, services, notes and scheduling',
    Icon: ISNIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo(function ISNComponent(props: NodeProps) {
        return <AutomationNode {...props} Icon={ISNIcon} iconColor="" />;
    }),
};
