import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const HiverIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/hiver.svg" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
HiverIcon.displayName = 'HiverIcon';

// Exact publisher asset; provenance is recorded beside the icon.
export const HiverNode: NodeDefinition = {
    type: 'automation-hiver',
    label: 'Hiver',
    description: 'Manage shared inboxes, tags, conversations, notes and drafts',
    category: 'support',
    Icon: HiverIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={HiverIcon} iconColor="" />),
};
