// Exposes Apache Superset in the workflow palette and analytics catalog.
// The backend schema supplies its REST operations, API key fields and poll triggers.
import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const SupersetIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/superset.svg" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
SupersetIcon.displayName = 'SupersetIcon';

// Exact publisher asset; provenance is recorded beside the SVG.
export const SupersetNode: NodeDefinition = {
    type: 'automation-superset',
    label: 'Superset',
    description: 'Dashboards, charts, datasets and change monitoring',
    category: 'analytics-bi',
    Icon: SupersetIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={SupersetIcon} iconColor="" />),
};
