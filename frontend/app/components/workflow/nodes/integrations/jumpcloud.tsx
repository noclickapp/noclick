import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const JumpCloudIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <ThemedBrandImg light="/icons/jumpcloud.svg" dark="/icons/jumpcloud-dark.svg" className={className} style={style} {...props} ref={ref} />
    ),
);
JumpCloudIcon.displayName = 'JumpCloudIcon';

// Exact publisher asset; provenance is recorded beside the icon.
export const JumpCloudNode: NodeDefinition = {
    type: 'automation-jumpcloud',
    label: 'JumpCloud',
    category: 'developer-tools',
    description: 'Manage directory users, devices, groups and membership',
    Icon: JumpCloudIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={JumpCloudIcon} iconColor="" />),
};
