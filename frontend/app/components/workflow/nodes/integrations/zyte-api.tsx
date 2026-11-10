import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const ZyteApiIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/zyte-api.png" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
ZyteApiIcon.displayName = 'ZyteApiIcon';

// Exact publisher asset; provenance is recorded beside the PNG.
export const ZyteApiNode: NodeDefinition = {
    type: 'automation-zyte-api',
    label: 'Zyte API',
    description: 'Extract web pages, products, articles, jobs and search results',
    category: 'content-research',
    Icon: ZyteApiIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={ZyteApiIcon} iconColor="" />),
};
