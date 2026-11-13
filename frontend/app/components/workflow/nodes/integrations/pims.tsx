import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';
import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';

const PimsIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <ThemedBrandImg light="/icons/pims.svg" className={className} style={style} {...props} ref={ref} />
    ),
);
PimsIcon.displayName = 'PimsIcon';

export const PimsNode: NodeDefinition = {
    type: 'automation-pims',
    label: 'Pims',
    description: 'Manage events and promotions, read ticket sales, and watch new or updated events.',
    category: 'industry',
    Icon: PimsIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={PimsIcon} iconColor="" />),
};
