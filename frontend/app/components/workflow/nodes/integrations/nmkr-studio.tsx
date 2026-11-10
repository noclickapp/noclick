import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const NmkrStudioIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/nmkr-studio.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const NmkrStudioNode: NodeDefinition = {
    type: 'automation-nmkr-studio', category: 'industry', label: 'NMKR Studio',
    description: 'Manage NFT projects, mint tokens, edit sales settings and whitelists',
    keywords: ['nmkr', 'nft', 'cardano', 'minting', 'blockchain'],
    Icon: NmkrStudioIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={NmkrStudioIcon} iconColor="" />),
};
