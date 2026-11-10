// Zendesk Support automation node definition.
// Provides workflow integration with the Zendesk Support v2 API (tickets, users,
// organizations, search, metadata) plus a webhook trigger for ticket events.

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';
import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const ZendeskIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>((props, ref) => (
    <ThemedBrandImg ref={ref} light="/icons/zendesk-light.svg" dark="/icons/zendesk.svg" {...props} />
));
ZendeskIcon.displayName = 'ZendeskIcon';

const ZendeskNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={ZendeskIcon} iconColor="" />;
};

export const ZendeskNode: NodeDefinition = {
    type: 'automation-zendesk',
    label: 'Zendesk',
    description: 'Zendesk Support automation',
    Icon: ZendeskIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(ZendeskNodeComponent),
};
