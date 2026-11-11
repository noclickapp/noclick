import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';
import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const ReplizIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => <ThemedBrandImg {...props} light="/icons/repliz.svg" dark="/icons/repliz-dark.svg" ref={ref} className={className} style={style} />,
);
ReplizIcon.displayName = 'ReplizIcon';
export const ReplizNode: NodeDefinition = {
    type: 'automation-repliz', label: 'Repliz', description: 'Manage social comments, contacts, messages and scheduled posts',
    category: 'social-media', Icon: ReplizIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={ReplizIcon} iconColor="" />),
};
