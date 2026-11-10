// Adds BFL to the workflow canvas and integration catalog.
// Its schema and credential metadata are generated from the BFL node.
import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const BflIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <ThemedBrandImg light="/icons/bfl.svg" dark="/icons/bfl-dark.svg" className={className} style={style} {...props} ref={ref} />
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
