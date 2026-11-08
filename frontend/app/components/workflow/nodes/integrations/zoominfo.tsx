import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const ZoomInfoIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/zoominfo.svg" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
ZoomInfoIcon.displayName = 'ZoomInfoIcon';

// Exact publisher asset; provenance is recorded beside the SVG.
export const ZoomInfoNode: NodeDefinition = {
    type: 'automation-zoominfo',
    label: 'ZoomInfo',
    description: 'Search and enrich prospects, inspect usage, and manage audiences',
    Icon: ZoomInfoIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={ZoomInfoIcon} iconColor="" />),
};
