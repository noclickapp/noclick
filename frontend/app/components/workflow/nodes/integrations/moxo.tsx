import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const MoxoIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/moxo.png" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
MoxoIcon.displayName = 'MoxoIcon';

// Exact publisher asset; provenance is recorded beside the icon.
export const MoxoNode: NodeDefinition = {
    type: 'automation-moxo',
    label: 'Moxo',
    description: 'Run flows, complete steps and collaborate in Moxo',
    category: 'productivity',
    Icon: MoxoIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={MoxoIcon} iconColor="" />),
};
