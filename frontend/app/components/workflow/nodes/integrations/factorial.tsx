import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const FactorialIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/factorial.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const FactorialNode: NodeDefinition = {
    type: 'automation-factorial', category: 'hr-recruiting', label: 'Factorial',
    description: 'Automate employees, leave requests, teams, tasks and candidates; receive HR events',
    keywords: ['HR', 'human resources', 'time off', 'recruitment', 'attendance'],
    Icon: FactorialIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={FactorialIcon} iconColor="" />),
};
