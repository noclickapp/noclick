import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const CasebookIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/casebook.png" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
CasebookIcon.displayName = 'CasebookIcon';

// Exact publisher asset; provenance is recorded beside the PNG.
export const CasebookNode: NodeDefinition = {
    type: 'automation-casebook',
    label: 'Casebook',
    description: 'Cases, people, intake reports, notes and service enrollments',
    category: 'nonprofit',
    Icon: CasebookIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={CasebookIcon} iconColor="" />),
};
