import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const TeamUpIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/teamup.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const TeamUpNode: NodeDefinition = {
    type: 'automation-teamup', category: 'bookings', label: 'TeamUp',
    description: 'Manage fitness customers, registrations, attendance and memberships; trigger on class registrations',
    Icon: TeamUpIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={TeamUpIcon} iconColor="" />),
};
