import { forwardRef, memo } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import type { NodeDefinition, SvgIconComponent } from './types';

const StreamChatIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/stream-chat.svg" alt="" className={className} style={{ filter: 'brightness(0) invert(1)', ...style }} {...props} />
    ),
);
StreamChatIcon.displayName = 'StreamChatIcon';

export const StreamChatNode: NodeDefinition = {
    type: 'automation-stream-chat',
    label: 'Stream Chat',
    description: 'Manage chat users and channels; read bounded message metadata',
    Icon: StreamChatIcon,
    iconColor: '#005FFF',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={StreamChatIcon} iconColor="#005FFF" />),
};
