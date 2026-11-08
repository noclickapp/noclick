/** Registers Manyreach in the integration catalog and workflow canvas.
 * Uses the publisher icon to identify the outreach operations generated from the backend schema. */
import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const ManyreachIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/manyreach.svg" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
ManyreachIcon.displayName = 'ManyreachIcon';

// Exact publisher asset; provenance is recorded beside the SVG.
export const ManyreachNode: NodeDefinition = {
    type: 'automation-manyreach',
    label: 'Manyreach',
    description: 'Automate outreach campaigns, prospects, lists and tags',
    category: 'marketing',
    Icon: ManyreachIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={ManyreachIcon} iconColor="" />),
};
