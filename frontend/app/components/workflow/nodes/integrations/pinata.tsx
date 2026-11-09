// Pinata's self-registering definition exposes the generated file and IPFS operations.
// The official provider mark identifies JWT connections throughout the workflow UI.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const PinataIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/pinata.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const PinataNode: NodeDefinition = {
    type: 'automation-pinata', category: 'databases-storage', label: 'Pinata',
    description: 'Manage IPFS files, groups, pin requests, swaps and JSON pins',
    keywords: ['IPFS', 'storage', 'CID', 'pinning'],
    Icon: PinataIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={PinataIcon} iconColor="" />),
};
