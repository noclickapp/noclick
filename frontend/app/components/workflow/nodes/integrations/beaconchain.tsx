// Exposes Beaconchain in the workflow palette and integrations directory.
// Uses the official provider icon so people can identify the service.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const BeaconchainIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <>
        <img src="/icons/beaconchain.svg" alt="" aria-hidden="true" className={`${className ?? ''} dark:hidden`}
            style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
        <img src="/icons/beaconchain-dark.svg" alt="" aria-hidden="true" className={`${className ?? ''} hidden dark:block`}
            style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
    </>
);

export const BeaconchainNode: NodeDefinition = {
    type: 'automation-beaconchain', category: 'developer-tools', label: 'Beaconchain',
    description: 'Read Ethereum validators, rewards, slots and balances; submit system metrics',
    Icon: BeaconchainIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={BeaconchainIcon} iconColor="" />),
};
