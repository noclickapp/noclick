import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const MicrosoftTeamsEventsIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/microsoft-teams-events.svg" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
MicrosoftTeamsEventsIcon.displayName = 'MicrosoftTeamsEventsIcon';

// Exact publisher asset; provenance is recorded beside the SVG.
export const MicrosoftTeamsEventsNode: NodeDefinition = {
    type: 'automation-microsoft-teams-events',
    label: 'Microsoft Teams Events',
    description: 'Create and manage Teams webinars, presenters and registration questions',
    category: 'microsoft',
    Icon: MicrosoftTeamsEventsIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={MicrosoftTeamsEventsIcon} iconColor="" />),
};
