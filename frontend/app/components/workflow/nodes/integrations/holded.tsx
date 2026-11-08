import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const HoldedIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/holded.png" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
HoldedIcon.displayName = 'HoldedIcon';

// Exact publisher asset; provenance is recorded beside the icon.
export const HoldedNode: NodeDefinition = {
    type: 'automation-holded',
    label: 'Holded',
    description: 'Contacts, invoices, products, projects and tasks',
    category: 'finance-accounting',
    Icon: HoldedIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={HoldedIcon} iconColor="" />),
};
