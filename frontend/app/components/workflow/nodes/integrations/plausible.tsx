import { forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const PlausibleIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/plausible.svg" alt="" className={className} style={style} {...props} />
    ),
);
PlausibleIcon.displayName = 'PlausibleIcon';

const PlausibleNodeComponent = (props: NodeProps) => <AutomationNode {...props} Icon={PlausibleIcon} iconColor="" />;

export const PlausibleNode: NodeDefinition = {
    type: 'automation-plausible',
    label: 'Plausible Analytics',
    description: 'Query analytics, record events, and manage Plausible sites',
    category: 'analytics-bi',
    Icon: PlausibleIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: PlausibleNodeComponent,
};
