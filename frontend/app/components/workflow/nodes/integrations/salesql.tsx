import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const SalesQLIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/salesql.svg" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
SalesQLIcon.displayName = 'SalesQLIcon';

// Exact publisher asset; provenance is recorded beside the SVG.
export const SalesQLNode: NodeDefinition = {
    type: 'automation-salesql',
    label: 'SalesQL',
    description: 'Enrich people and companies, verify emails and track credits',
    category: 'crm-sales',
    keywords: ['lead enrichment', 'email verification', 'prospecting'],
    Icon: SalesQLIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={SalesQLIcon} iconColor="" />),
};
