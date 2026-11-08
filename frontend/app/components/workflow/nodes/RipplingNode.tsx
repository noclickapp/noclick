import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

// Unmodified Rippling artwork from the official newsroom's brand asset ZIP.
const RipplingIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/rippling.svg" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    )
);
RipplingIcon.displayName = 'RipplingIcon';
export const RipplingNode: NodeDefinition = {
    type: 'automation-rippling',
    label: 'Rippling',
    description: 'Employees, departments, leave and supergroups',
    category: 'hr-recruiting',
    keywords: ['HR', 'HRIS', 'employees', 'workers', 'PTO', 'time off', 'groups'],
    Icon: RipplingIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={RipplingIcon} iconColor="" />),
};
