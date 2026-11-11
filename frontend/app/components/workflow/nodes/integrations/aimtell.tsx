// Adds Aimtell to the workflow palette and integration catalog. The official
// documentation icon identifies its API-key campaign and subscriber actions.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const AimtellIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/aimtell.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const AimtellNode: NodeDefinition = {
    type: 'automation-aimtell', category: 'marketing', label: 'Aimtell',
    description: 'Manage push campaigns, segments, subscribers and website variables',
    keywords: ['web push', 'notifications', 'subscribers', 'segments'],
    Icon: AimtellIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={AimtellIcon} iconColor="" />),
};
