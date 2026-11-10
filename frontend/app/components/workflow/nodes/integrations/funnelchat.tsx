import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const FunnelchatIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/funnelchat.svg" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
FunnelchatIcon.displayName = 'FunnelchatIcon';

export const FunnelchatNode: NodeDefinition = {
    type: 'automation-funnelchat',
    label: 'Funnelchat',
    description: 'WhatsApp messages, contacts, tags, custom fields and signed events',
    category: 'communication',
    keywords: ['WhatsApp', 'messaging', 'contacts'],
    Icon: FunnelchatIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={FunnelchatIcon} iconColor="" />),
};
