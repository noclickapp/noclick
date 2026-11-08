import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const RagicIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => <img ref={ref} src="/icons/ragic.webp" alt="" className={className} style={style} {...props} />
);
RagicIcon.displayName = 'RagicIcon';
const RagicNodeComponent = (props: NodeProps) => <AutomationNode {...props} Icon={RagicIcon} iconColor="#19191b" />;
export const RagicNode: NodeDefinition = {
    type: 'automation-ragic', label: 'Ragic',
    description: 'Read and search explicitly projected sheet records',
    Icon: RagicIcon, iconColor: '#19191b', dimensions: { width: 90, height: 90, iconSize: 48 }, component: memo(RagicNodeComponent),
};
