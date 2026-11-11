import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const RoyalMailIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <>
        <img src="/icons/royalmail.svg" alt="" aria-hidden="true" className={`${className ?? ''} dark:hidden`} style={style} />
        <img src="/icons/royalmail-dark.svg" alt="" aria-hidden="true" className={`${className ?? ''} hidden dark:block`} style={style} />
    </>
);

export const RoyalMailNode: NodeDefinition = {
    type: 'automation-royalmail', label: 'ChannelShipper & Royal Mail', category: 'ecommerce',
    description: 'Import orders, generate shipping documents, manage manifests and returns, and watch for new orders',
    keywords: ['Royal Mail', 'ChannelShipper', 'Click & Drop', 'shipping', 'postage'],
    Icon: RoyalMailIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={RoyalMailIcon} iconColor="" />),
};
