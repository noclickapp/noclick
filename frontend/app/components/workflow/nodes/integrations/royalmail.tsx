import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';
import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';

const RoyalMailIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/royalmail.svg" dark="/icons/royalmail-dark.svg" className={className} style={style} />
);

export const RoyalMailNode: NodeDefinition = {
    type: 'automation-royalmail', label: 'ChannelShipper & Royal Mail', category: 'ecommerce',
    description: 'Import orders, generate shipping documents, manage manifests and returns, and watch for new orders',
    keywords: ['Royal Mail', 'ChannelShipper', 'Click & Drop', 'shipping', 'postage'],
    Icon: RoyalMailIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={RoyalMailIcon} iconColor="" />),
};
