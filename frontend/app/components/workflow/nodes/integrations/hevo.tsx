import { forwardRef, type ImgHTMLAttributes } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const HevoIcon = forwardRef<HTMLImageElement, ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <ThemedBrandImg light="/icons/hevo.svg" dark="/icons/hevo-dark.svg" className={className} style={style} {...props} ref={ref} />
    ),
);
HevoIcon.displayName = 'HevoIcon';

export const HevoNode: NodeDefinition = {
    type: 'automation-hevo',
    label: 'Hevo',
    description: 'Regional pipeline, source and destination metadata, scheduling and workflow status',
    category: 'analytics-bi',
    Icon: HevoIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: (props: NodeProps) => <AutomationNode {...props} Icon={HevoIcon} iconColor="" />,
};
