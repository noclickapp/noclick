import { forwardRef } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const CoveoIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => <img ref={ref} src="/icons/coveo.svg" alt="" className={className} style={style} {...props} />,
);
CoveoIcon.displayName = 'CoveoIcon';
const Component = (props: NodeProps) => <AutomationNode {...props} Icon={CoveoIcon} iconColor="" />;
export const CoveoNode: NodeDefinition = {
    type: 'automation-coveo', label: 'Coveo', description: 'Search indexed metadata, inspect fields and sources, and manage source refresh jobs.',
    Icon: CoveoIcon, iconColor: '', dimensions: { width: 110, height: 90, iconSize: 48 }, component: Component,
};
