import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const MistIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style }, ref) => (
        <img ref={ref} src="/icons/mist.svg" alt="" className={className} style={style} />
    ),
);
MistIcon.displayName = 'MistIcon';

export const MistNode: NodeDefinition = {
    type: 'automation-mist',
    label: 'Mist API',
    description: 'Automate Juniper Mist sites, devices, Wi-Fi networks and alarms',
    category: 'monitoring',
    keywords: ['juniper', 'mist', 'wifi', 'network', 'access point'],
    Icon: MistIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={MistIcon} iconColor="" />),
};
