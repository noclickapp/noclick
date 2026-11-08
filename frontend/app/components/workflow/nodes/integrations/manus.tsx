import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const ManusIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/manus.svg" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
ManusIcon.displayName = 'ManusIcon';

// Exact publisher asset; provenance is recorded beside the SVG.
export const ManusNode: NodeDefinition = {
    type: 'automation-manus',
    label: 'Manus',
    description: 'Automate tasks, messages, projects, files and webhooks',
    category: 'ai',
    Icon: ManusIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={ManusIcon} iconColor="" />),
};
