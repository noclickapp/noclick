// Composio exposes project tools, connected accounts and trigger management.
// This definition makes the self-registering integration discoverable on the canvas and catalog.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const ComposioIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/composio.svg" dark="/icons/composio-dark.svg" className={className} style={style} />
);

export const ComposioNode: NodeDefinition = {
    type: 'automation-composio', category: 'developer-tools', label: 'Composio',
    description: 'Discover and execute tools, manage auth configurations, connected accounts and triggers',
    Icon: ComposioIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={ComposioIcon} iconColor="" />),
};
