/** Exposes OpenSea in integration discovery and the workflow canvas.
 * The shared automation renderer presents its backend-generated configuration. */
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const OpenSeaIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/open-sea.svg" className={className} style={style} />
);

export const OpenSeaNode: NodeDefinition = {
    type: 'automation-open-sea', category: 'finance-accounting', label: 'OpenSea',
    description: 'Find NFTs, track collection and wallet events, refresh metadata, and submit signed listings and offers',
    keywords: ['Open Sea', 'NFT', 'Seaport', 'wallet', 'collectibles', 'sales', 'transfers'],
    Icon: OpenSeaIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={OpenSeaIcon} iconColor="" />),
};
