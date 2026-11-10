import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const GleifIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/gleif.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const GleifNode: NodeDefinition = {
    type: 'automation-gleif', category: 'finance-accounting', label: 'GLEIF',
    description: 'Look up legal entities, ownership relationships and LEI registration data',
    Icon: GleifIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={GleifIcon} iconColor="" />),
};
