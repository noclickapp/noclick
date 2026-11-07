import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const StaffbaseIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/staffbase.svg" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
StaffbaseIcon.displayName = 'StaffbaseIcon';

// Exact publisher asset; provenance is recorded beside the SVG.
export const StaffbaseNode: NodeDefinition = {
    type: 'automation-staffbase',
    label: 'Staffbase',
    description: 'Tenant users, groups, news and draft pages',
    Icon: StaffbaseIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={StaffbaseIcon} iconColor="" />),
};
