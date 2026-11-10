import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const SavvyCalIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <ThemedBrandImg light="/icons/savvycal.svg" dark="/icons/savvycal-dark.svg" className={className} style={style} {...props} ref={ref} />
    ),
);
SavvyCalIcon.displayName = 'SavvyCalIcon';

export const SavvyCalNode: NodeDefinition = {
    type: 'automation-savvycal',
    label: 'SavvyCal',
    description: 'Book and cancel events, find available times, and manage scheduling links and webhooks.',
    category: 'meetings',
    keywords: ['calendar', 'scheduling', 'booking', 'availability'],
    Icon: SavvyCalIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={SavvyCalIcon} iconColor="" />),
};
