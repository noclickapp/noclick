// Affinity CRM automation node definition.
// Provides workflow integration with Affinity CRM for persons, organizations,
// opportunities, lists, notes, reminders, and relationship strengths.

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const AffinityIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img
            ref={ref}
            src="/icons/affinity.svg"
            alt=""
            className={className}
            style={style}
            {...props}
        />
    )
);
AffinityIcon.displayName = 'AffinityIcon';

const AffinityNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={AffinityIcon} iconColor="" />;
};

export const AffinityNode: NodeDefinition = {
    type: 'automation-affinity',
    label: 'Affinity',
    description: 'Affinity CRM automation',
    Icon: AffinityIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(AffinityNodeComponent),
};
