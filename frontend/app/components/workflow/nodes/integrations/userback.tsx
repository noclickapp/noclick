import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import {
    NodeDefinition,
    SvgIconComponent,
} from '~/components/workflow/nodes/types';

const UserbackIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <img
        ref={ref}
        src="/icons/userback.svg"
        alt=""
        className={className}
        style={{ ...style, objectFit: 'contain' }}
        {...props}
    />
));
UserbackIcon.displayName = 'UserbackIcon';

const UserbackComponent = memo(function UserbackComponent(props: NodeProps) {
    return <AutomationNode {...props} Icon={UserbackIcon} iconColor="" />;
});

// Exact publisher asset; provenance is recorded beside the PNG.
export const UserbackNode: NodeDefinition = {
    type: 'automation-userback',
    label: 'Userback',
    description: 'Manage feedback, comments, projects and workflow statuses',
    category: 'support',
    Icon: UserbackIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: UserbackComponent,
};
