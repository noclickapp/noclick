import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const FuseaiIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/fuseai.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const FuseaiNode: NodeDefinition = {
    type: 'automation-fuseai', category: 'crm-sales', label: 'Fuseai',
    description: 'Manage prospect lists and campaigns, find emails and verify contact data',
    Icon: FuseaiIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={FuseaiIcon} iconColor="" />),
};
