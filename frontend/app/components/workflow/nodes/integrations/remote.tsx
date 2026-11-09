import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const RemoteIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/remote.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const RemoteNode: NodeDefinition = {
    type: 'automation-remote', category: 'hr-recruiting', label: 'Remote',
    description: 'Manage employees, time off, expenses, incentives and timesheets; receive Remote events',
    Icon: RemoteIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={RemoteIcon} iconColor="" />),
};
