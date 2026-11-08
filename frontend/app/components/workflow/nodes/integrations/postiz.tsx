import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

export const PostizIcon: SvgIconComponent = forwardRef<
    HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <img ref={ref} src="/icons/postiz.svg" alt="" className={className} style={style} {...props} />
));
PostizIcon.displayName = 'PostizIcon';

const PostizNodeComponent = (props: NodeProps) => (
    <AutomationNode {...props} Icon={PostizIcon} iconColor="" />
);

export const PostizNode: NodeDefinition = {
    type: 'automation-postiz', category: 'social-media', label: 'Postiz',
    description: 'Social channels, scheduling, analytics, media and video', Icon: PostizIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo(PostizNodeComponent),
};
