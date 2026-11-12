// Defines Cling in the workflow canvas and integration catalog.
// Its schema and credentials are discovered from the backend-generated metadata.
import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const ClingIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/cling.svg" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
ClingIcon.displayName = 'ClingIcon';

// Exact publisher asset; provenance is recorded beside the SVG.
export const ClingNode: NodeDefinition = {
    type: 'automation-cling',
    label: 'Cling',
    description: 'Create and send agreements, manage customers and projects, and react to accepted documents',
    category: 'documents',
    Icon: ClingIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={ClingIcon} iconColor="" />),
};
