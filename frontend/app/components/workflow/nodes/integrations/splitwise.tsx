import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const SplitwiseIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/splitwise.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const SplitwiseNode: NodeDefinition = {
    type: 'automation-splitwise', category: 'finance-accounting', label: 'Splitwise',
    description: 'Manage shared expenses, groups, friends and comments',
    Icon: SplitwiseIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={SplitwiseIcon} iconColor="" />),
};
