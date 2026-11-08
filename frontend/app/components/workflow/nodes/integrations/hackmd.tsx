import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const HackMDIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/hackmd.png" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
HackMDIcon.displayName = 'HackMDIcon';

// Exact publisher asset; provenance is recorded beside the icon.
export const HackMDNode: NodeDefinition = {
    type: 'automation-hackmd',
    label: 'HackMD',
    description: 'Create and manage Markdown notes, team notes and folders',
    category: 'documents',
    Icon: HackMDIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={HackMDIcon} iconColor="" />),
};
