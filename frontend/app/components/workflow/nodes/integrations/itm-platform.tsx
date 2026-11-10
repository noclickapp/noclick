import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const ITMPlatformIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/itm-platform.svg" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
ITMPlatformIcon.displayName = 'ITMPlatformIcon';

// Exact publisher asset; provenance is recorded beside the icon.
export const ITMPlatformNode: NodeDefinition = {
    type: 'automation-itm-platform',
    label: 'ITM Platform',
    description: 'Automate projects, tasks, services and timesheets',
    category: 'productivity',
    Icon: ITMPlatformIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={ITMPlatformIcon} iconColor="" />),
};
