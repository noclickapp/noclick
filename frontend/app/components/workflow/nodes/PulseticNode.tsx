import { forwardRef, memo } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const PulseticIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/pulsetic.svg" alt="" className={className}
            style={{ objectFit: 'contain', ...style }} {...props} />
    )
);
PulseticIcon.displayName = 'PulseticIcon';

export const PulseticNode: NodeDefinition = {
    type: 'automation-pulsetic',
    label: 'Pulsetic',
    description: 'Read monitor, uptime/history, heartbeat and status-page metadata',
    category: 'monitoring',
    keywords: ['pulsetic', 'monitoring', 'uptime', 'downtime', 'heartbeat', 'status page'],
    Icon: PulseticIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={PulseticIcon} iconColor="" />),
};
