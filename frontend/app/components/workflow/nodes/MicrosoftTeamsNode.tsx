// Microsoft Teams automation node definition.
// Provides workflow integration with Microsoft Teams via the Microsoft Graph API
// (teams, channels, messages, chats, members, apps, tabs, meetings, presence)
// plus a webhook trigger for Graph change notifications. Added to wire the
// Microsoft Teams integration into the visual workflow editor.

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const MicrosoftTeamsIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <img
        ref={ref}
        src="/icons/microsoft-teams.svg"
        alt=""
        className={className}
        style={style}
        {...props}
    />
));
MicrosoftTeamsIcon.displayName = 'MicrosoftTeamsIcon';

const MicrosoftTeamsNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={MicrosoftTeamsIcon} iconColor="" />;
};

export const MicrosoftTeamsNode: NodeDefinition = {
    type: 'automation-microsoft-teams',
    label: 'Microsoft Teams',
    description: 'Microsoft Teams automation',
    Icon: MicrosoftTeamsIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(MicrosoftTeamsNodeComponent),
};
