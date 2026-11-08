import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const PostmarkIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <img
        ref={ref}
        src="/icons/postmark.svg"
        alt=""
        className={className}
        style={style}
        {...props}
    />
));
PostmarkIcon.displayName = 'PostmarkIcon';

const PostmarkNodeComponent = (props: NodeProps) => (
    <AutomationNode {...props} Icon={PostmarkIcon} iconColor="" />
);

export const PostmarkNode: NodeDefinition = {
    type: 'automation-postmark',
    label: 'Postmark',
    description: 'Send and track email, manage templates, streams, suppressions, and webhooks',
    category: 'communication',
    Icon: PostmarkIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(PostmarkNodeComponent),
};
