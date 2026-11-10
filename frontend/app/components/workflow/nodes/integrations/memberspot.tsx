import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const MemberspotIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <ThemedBrandImg light="/icons/memberspot.svg" dark="/icons/memberspot-dark.svg" className={className} style={style} {...props} ref={ref} />
    ),
);
MemberspotIcon.displayName = 'MemberspotIcon';

// Official publisher icon; provenance is recorded beside the asset.
export const MemberspotNode: NodeDefinition = {
    type: 'automation-memberspot',
    label: 'Memberspot',
    description: 'Members, course access, learning progress and exams',
    category: 'courses',
    Icon: MemberspotIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={MemberspotIcon} iconColor="" />),
};
