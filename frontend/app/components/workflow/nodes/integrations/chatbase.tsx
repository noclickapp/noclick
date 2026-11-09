import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const ChatbaseIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/chatbase.png" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
ChatbaseIcon.displayName = 'ChatbaseIcon';

// Exact publisher asset; provenance is recorded beside the icon.
export const ChatbaseNode: NodeDefinition = {
    type: 'automation-chatbase',
    label: 'Chatbase',
    description: 'Manage AI agents, chat, conversations, knowledge sources and support tickets',
    category: 'ai',
    Icon: ChatbaseIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={ChatbaseIcon} iconColor="" />),
};
