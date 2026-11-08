// Gorgias feedback and roadmap automation node.

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const GorgiasIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <img
        ref={ref}
        src="/icons/gorgias.svg"
        alt=""
        className={className}
        style={style}
        {...props}
    />
));
GorgiasIcon.displayName = 'GorgiasIcon';

const GorgiasNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={GorgiasIcon} iconColor="" />;
};

export const GorgiasNode: NodeDefinition = {
    type: 'automation-gorgias',
    label: 'Gorgias',
    description: 'Tickets, customers, messages, tags, and settings',
    category: 'support',
    Icon: GorgiasIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(GorgiasNodeComponent),
};
