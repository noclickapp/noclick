// Project Broadcast uses the shared automation canvas and generated configuration.
// The official provider mark identifies the API-key connection in the catalog.
import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const ProjectBroadcastIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/project-broadcast.webp" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
ProjectBroadcastIcon.displayName = 'ProjectBroadcastIcon';

// Exact publisher asset; provenance is recorded beside the image.
export const ProjectBroadcastNode: NodeDefinition = {
    type: 'automation-project-broadcast',
    label: 'Project Broadcast',
    description: 'Manage contacts, send messages, and automate campaigns',
    category: 'marketing',
    Icon: ProjectBroadcastIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={ProjectBroadcastIcon} iconColor="" />),
};
