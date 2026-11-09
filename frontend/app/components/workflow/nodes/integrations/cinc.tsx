import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const CINCIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/cinc.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const CINCNode: NodeDefinition = {
    type: 'automation-cinc', category: 'crm-sales', label: 'CINC',
    description: 'Manage CINC leads, notes, agents and labels',
    Icon: CINCIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={CINCIcon} iconColor="" />),
};
