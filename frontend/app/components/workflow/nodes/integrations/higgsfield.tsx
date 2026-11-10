import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const HiggsfieldIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <ThemedBrandImg light="/icons/higgsfield.svg" dark="/icons/higgsfield-dark.svg" className={className} style={style} {...props} ref={ref} />
    ),
);
HiggsfieldIcon.displayName = 'HiggsfieldIcon';

// Official documentation icon; provenance is recorded beside the asset.
export const HiggsfieldNode: NodeDefinition = {
    type: 'automation-higgsfield',
    label: 'Higgsfield',
    description: 'Generate images and videos, retrieve outputs, cancel and delete requests',
    category: 'ai',
    Icon: HiggsfieldIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={HiggsfieldIcon} iconColor="" />),
};
