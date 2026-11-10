import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const PimsIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/pims.png" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
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
