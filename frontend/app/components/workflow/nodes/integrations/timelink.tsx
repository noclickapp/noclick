// Registers Timelink in the workflow canvas and integration catalog.
// Its publisher icon and productivity category help people find time tracking actions.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const TimelinkIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/timelink.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const TimelinkNode: NodeDefinition = {
    type: 'automation-timelink',
    category: 'productivity',
    label: 'Timelink',
    description: 'Track time and manage clients, projects, services and time entries',
    keywords: ['time tracking', 'timesheets', 'billable hours'],
    Icon: TimelinkIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 52 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={TimelinkIcon} iconColor="" />),
};
