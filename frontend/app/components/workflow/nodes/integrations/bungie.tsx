// Bungie API node for Destiny account reads, game actions and completed activity polling.
// The official Bungie favicon identifies the provider throughout the workflow UI.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const BungieIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/bungie.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const BungieNode: NodeDefinition = {
    type: 'automation-bungie', category: 'media', label: 'Bungie.Net API',
    description: 'Read Destiny profiles and activities, manage items and loadouts, and watch completed activities',
    keywords: ['bungie', 'destiny', 'destiny 2', 'inventory', 'loadout', 'activity'],
    Icon: BungieIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={BungieIcon} iconColor="" />),
};
