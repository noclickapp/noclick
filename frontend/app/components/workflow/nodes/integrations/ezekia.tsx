import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const EzekiaIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <ThemedBrandImg light="/icons/ezekia.svg" dark="/icons/ezekia-dark.svg" className={className} style={style} {...props} ref={ref} />
    ),
);
EzekiaIcon.displayName = 'EzekiaIcon';

// Exact publisher asset; provenance is recorded beside the SVG.
export const EzekiaNode: NodeDefinition = {
    type: 'automation-ezekia',
    label: 'Ezekia',
    description: 'Manage recruiting people, companies, search projects and tasks',
    category: 'hr-recruiting',
    Icon: EzekiaIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={EzekiaIcon} iconColor="" />),
};
