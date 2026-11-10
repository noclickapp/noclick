import { forwardRef, type ImgHTMLAttributes } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const IterableIcon = forwardRef<HTMLImageElement, ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <ThemedBrandImg {...props} light="/icons/iterable-preferred-brand.svg" dark="/icons/iterable-preferred-brand-dark.svg" className={className} style={style} ref={ref} />
    ),
);
IterableIcon.displayName = 'IterableIcon';

export const IterableNode: NodeDefinition = {
    type: 'automation-iterable',
    label: 'Iterable',
    description: 'Iterable users, lists, events, campaigns, templates, and journeys',
    category: 'marketing',
    Icon: IterableIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: (props: NodeProps) => <AutomationNode {...props} Icon={IterableIcon} iconColor="" />,
};
