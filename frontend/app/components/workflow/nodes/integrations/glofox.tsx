// Native canvas definition for the typed Glofox operations. The vendor portal
// mark is served locally so canvas rendering never contacts the provider.
import { forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

// Exact vendor API-portal mark; provenance is beside the asset.
const GlofoxIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => <img ref={ref} src="/icons/glofox.svg" alt="" className={className} style={style} {...props} />,
);
GlofoxIcon.displayName = 'GlofoxIcon';
const GlofoxNodeComponent = (props: NodeProps) => <AutomationNode {...props} Icon={GlofoxIcon} iconColor="" />;

export const GlofoxNode: NodeDefinition = {
    type: 'automation-glofox',
    label: 'Glofox',
    category: 'industry',
    description: 'Branch members, classes, booking metadata and lead notes',
    Icon: GlofoxIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: GlofoxNodeComponent,
};
