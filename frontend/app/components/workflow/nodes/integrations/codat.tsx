import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const CodatIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/codat.png" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
CodatIcon.displayName = 'CodatIcon';

// Exact publisher asset; provenance is recorded beside the image.
export const CodatNode: NodeDefinition = {
    type: 'automation-codat',
    label: 'Assess API',
    keywords: ['Codat', 'financial insights', 'loan reports', 'data integrity'],
    description: 'Codat financial reports, data integrity and read completion events',
    category: 'finance-accounting',
    Icon: CodatIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={CodatIcon} iconColor="" />),
};
