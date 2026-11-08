import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const NozbeTeamsIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/nozbe-teams.png" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
NozbeTeamsIcon.displayName = 'NozbeTeamsIcon';

// Exact publisher asset; provenance is recorded beside the PNG.
export const NozbeTeamsNode: NodeDefinition = {
    type: 'automation-nozbe-teams',
    label: 'Nozbe Teams',
    description: 'Manage Nozbe spaces, projects, tasks, comments and tags',
    Icon: NozbeTeamsIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={NozbeTeamsIcon} iconColor="" />),
};
