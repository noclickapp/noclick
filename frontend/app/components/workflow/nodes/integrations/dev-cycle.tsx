import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const DevCycleIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/dev-cycle.svg" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
DevCycleIcon.displayName = 'DevCycleIcon';

// Exact publisher asset; provenance is recorded beside the SVG.
export const DevCycleNode: NodeDefinition = {
    type: 'automation-dev-cycle',
    label: 'Dev Cycle',
    description: 'Manage feature flags, variables, projects and environments',
    category: 'developer-tools',
    Icon: DevCycleIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={DevCycleIcon} iconColor="" />),
};
