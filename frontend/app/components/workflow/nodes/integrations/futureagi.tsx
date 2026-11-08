import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const FutureagiIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/futureagi.svg" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
FutureagiIcon.displayName = 'FutureagiIcon';

// Exact publisher asset; provenance is recorded beside the SVG.
export const FutureagiNode: NodeDefinition = {
    type: 'automation-futureagi',
    label: 'Futureagi',
    description: 'Manage AI annotation labels, scores, and review queues',
    category: 'ai',
    Icon: FutureagiIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={FutureagiIcon} iconColor="" />),
};
