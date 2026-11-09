import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const BotConversaIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/botconversa.png" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
BotConversaIcon.displayName = 'BotConversaIcon';

// Exact publisher asset; provenance is recorded beside the PNG.
export const BotConversaNode: NodeDefinition = {
    type: 'automation-botconversa',
    label: 'BotConversa',
    description: 'Automate WhatsApp contacts, messages, flows and campaigns',
    category: 'communication',
    Icon: BotConversaIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={BotConversaIcon} iconColor="" />),
};
