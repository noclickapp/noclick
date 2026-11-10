import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const UnifiIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <ThemedBrandImg {...props} light="/icons/unifi.svg" className={className} style={style} ref={ref} />
    ),
);
UnifiIcon.displayName = 'UnifiIcon';

// Exact publisher asset; provenance is recorded beside the SVG.
export const UnifiNode: NodeDefinition = {
    type: 'automation-unifi',
    label: 'UniFi',
    description: 'UniFi hosts, sites, devices, ISP metrics and console applications',
    category: 'monitoring',
    Icon: UnifiIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={UnifiIcon} iconColor="" />),
};
