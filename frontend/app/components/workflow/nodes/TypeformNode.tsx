// Typeform REST API automation node definition.
// Provides workflow integration with Typeform for forms, themes, images, workspaces, responses, webhooks, and translations.

import { memo } from 'react';
import { NodeProps } from '@xyflow/react';
import { TypeformIcon } from '~/components/icons/TypeformIcon';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const TypeformNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={TypeformIcon} iconColor="text-foreground" />;
};

export const TypeformNode: NodeDefinition = {
    type: 'automation-typeform',
    label: 'Typeform',
    description: 'Typeform operations',
    Icon: TypeformIcon,
    iconColor: 'text-foreground',
    dimensions: DIMENSIONS,
    component: memo(TypeformNodeComponent),
};
