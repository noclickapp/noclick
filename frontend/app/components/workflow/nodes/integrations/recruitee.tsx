import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const RecruiteeIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/recruitee.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const RecruiteeNode: NodeDefinition = {
    type: 'automation-recruitee', label: 'Recruitee',
    description: 'Manage candidates and jobs; read notes, departments, members and locations',
    Icon: RecruiteeIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={RecruiteeIcon} iconColor="" />),
};
