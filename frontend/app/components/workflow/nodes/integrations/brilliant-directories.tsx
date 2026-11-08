import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const BrilliantDirectoriesIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/brilliant-directories.svg" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
BrilliantDirectoriesIcon.displayName = 'BrilliantDirectoriesIcon';

// Exact publisher asset; provenance is recorded beside the SVG.
export const BrilliantDirectoriesNode: NodeDefinition = {
    type: 'automation-brilliant-directories',
    label: 'Brilliant Directories',
    description: 'Manage directory members, leads, reviews, posts and membership plans',
    Icon: BrilliantDirectoriesIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={BrilliantDirectoriesIcon} iconColor="" />),
};
