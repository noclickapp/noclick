import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const VibeIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/vibe.png" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
VibeIcon.displayName = 'VibeIcon';

// Exact publisher asset; provenance is recorded beside the image.
export const VibeNode: NodeDefinition = {
    type: 'automation-vibe',
    label: 'Vibe',
    description: 'Manage CTV advertisers, campaigns, strategies, audiences and reports',
    category: 'marketing',
    Icon: VibeIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={VibeIcon} iconColor="" />),
};
