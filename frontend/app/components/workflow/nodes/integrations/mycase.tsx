import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const MyCaseIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/mycase.svg" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
MyCaseIcon.displayName = 'MyCaseIcon';

export const MyCaseNode: NodeDefinition = {
    type: 'automation-mycase',
    label: 'MyCase',
    description: 'Watch for new or updated cases, clients, leads and tasks; manage your legal practice',
    category: 'industry',
    Icon: MyCaseIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={MyCaseIcon} iconColor="" />),
};
