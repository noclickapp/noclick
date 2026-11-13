// ServiceM8's definition makes its account operations and job trigger discoverable.
// The provider's original icon is pinned with a provenance sidecar beside it.
import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const ServiceM8Icon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <ThemedBrandImg light="/icons/servicem8.svg" className={className} style={style} {...props} ref={ref} />
    ),
);
ServiceM8Icon.displayName = 'ServiceM8Icon';

export const ServiceM8Node: NodeDefinition = {
    type: 'automation-servicem8',
    label: 'ServiceM8',
    description: 'Jobs, clients, contacts, scheduling, tasks, notes and recorded payments',
    category: 'industry',
    keywords: ['servicem8', 'field service', 'dispatch', 'trades', 'job management'],
    Icon: ServiceM8Icon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={ServiceM8Icon} iconColor="" />),
};
