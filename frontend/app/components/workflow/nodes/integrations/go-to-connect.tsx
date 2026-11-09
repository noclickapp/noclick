// GoTo Connect calls, messaging, voicemail and presence automation.
// Uses the publisher's product logo, with provenance recorded beside the asset.
import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const GoToConnectIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/go-to-connect.svg" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
GoToConnectIcon.displayName = 'GoToConnectIcon';

export const GoToConnectNode: NodeDefinition = {
    type: 'automation-go-to-connect', label: 'GoTo Connect',
    description: 'Calls, text messages, voicemail, users and presence',
    category: 'communication', keywords: ['GoToConnect', 'Jive', 'SMS', 'phone'],
    Icon: GoToConnectIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={GoToConnectIcon} iconColor="" />),
};
