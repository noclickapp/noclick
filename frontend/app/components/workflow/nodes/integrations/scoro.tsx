import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const ScoroIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <ThemedBrandImg light="/icons/scoro.svg" dark="/icons/scoro-dark.svg" className={className} style={style} {...props} ref={ref} />
    ),
);
ScoroIcon.displayName = 'ScoroIcon';

export const ScoroNode: NodeDefinition = {
    type: 'automation-scoro',
    label: 'Scoro',
    description: 'Manage contacts, projects, tasks, time entries, quotes and invoices',
    category: 'productivity',
    Icon: ScoroIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={ScoroIcon} iconColor="" />),
};
