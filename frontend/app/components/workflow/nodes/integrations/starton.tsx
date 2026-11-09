// Starton exposes project smart contracts, wallets, transactions and IPFS actions.
// This definition makes its generated configuration available on the canvas and catalog.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const StartonIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/starton.jpg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const StartonNode: NodeDefinition = {
    type: 'automation-starton', label: 'Starton',
    category: 'developer-tools',
    description: 'Manage smart contracts, transactions, wallets and IPFS files in Starton',
    keywords: ['web3', 'blockchain', 'ethereum', 'ipfs', 'smart contract'],
    Icon: StartonIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={StartonIcon} iconColor="" />),
};
