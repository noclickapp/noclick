// Discover the self-hosted OpenWA gateway in the integration catalog and canvas.
// The icon uses the publisher's original app mark with its adjacent provenance.
import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const OpenWAIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img {...props} ref={ref} src="/icons/openwa.svg" alt="" className={className} style={style} />
    ),
);
OpenWAIcon.displayName = 'OpenWAIcon';

export const OpenWANode: NodeDefinition = {
    type: 'automation-openwa',
    label: 'OpenWA',
    description: 'Automate messaging, chats, contacts and groups on your OpenWA gateway',
    category: 'communication',
    keywords: ['WhatsApp', 'self-hosted', 'gateway'],
    Icon: OpenWAIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={OpenWAIcon} iconColor="" />),
};
