// Native NationBuilder CRM node definition. The icon is the unchanged official
// NationBuilder mark; configuration and credential forms use the native schema.
import { forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const NationBuilderIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <ThemedBrandImg light="/icons/nationbuilder.svg" dark="/icons/nationbuilder-dark.svg" className={className} style={style} {...props} ref={ref} />
    )
);
NationBuilderIcon.displayName = 'NationBuilderIcon';

export const NationBuilderNode: NodeDefinition = {
    type: 'automation-nationbuilder',
    label: 'NationBuilder',
    description: 'Manage nation signups, tags, custom lists and membership metadata',
    category: 'nonprofit',
    Icon: NationBuilderIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: (props: NodeProps) => <AutomationNode {...props} Icon={NationBuilderIcon} iconColor="" />,
};
