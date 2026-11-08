import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const PingdomIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/pingdom.svg" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
PingdomIcon.displayName = 'PingdomIcon';

// Exact publisher asset; provenance is recorded beside the icon.
export const PingdomNode: NodeDefinition = {
    type: 'automation-pingdom',
    label: 'Pingdom',
    category: 'monitoring',
    description: 'Uptime checks, maintenance windows, alerts and performance reports',
    Icon: PingdomIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={PingdomIcon} iconColor="" />),
};
