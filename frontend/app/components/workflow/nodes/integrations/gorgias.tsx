// Gorgias feedback and roadmap automation node.

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const GorgiasIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <ThemedBrandImg light="/icons/gorgias.svg" dark="/icons/gorgias-dark.svg" className={className} style={style} {...props} ref={ref} />
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
