// Adds BFL to the workflow canvas and integration catalog.
// Its schema and credential metadata are generated from the BFL node.
import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const BflIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/bfl.png" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
BflIcon.displayName = 'BflIcon';

// Exact publisher asset; provenance is recorded beside the PNG.
export const BflNode: NodeDefinition = {
    type: 'automation-bfl',
    label: 'BFL',
    description: 'Generate and edit FLUX images, poll tasks and manage finetunes',
    category: 'ai',
    Icon: BflIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={BflIcon} iconColor="" />),
};
