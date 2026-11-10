import { forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const DopplerIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/doppler.svg" alt="" className={className} style={style} {...props} />
    ),
);
DopplerIcon.displayName = 'DopplerIcon';

export const DopplerNode: NodeDefinition = {
    type: 'automation-doppler',
    label: 'Doppler',
    description: 'Manage projects, configs, environments, and secrets in Doppler',
    category: 'developer-tools',
    Icon: DopplerIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: (props: NodeProps) => <AutomationNode {...props} Icon={DopplerIcon} iconColor="" />,
};
