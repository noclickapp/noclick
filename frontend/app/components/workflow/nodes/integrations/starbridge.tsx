import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';
const StarbridgeIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/starbridge.png" alt="" aria-hidden="true" className={className} style={{ ...style, objectFit: 'contain' }} />
);
export const StarbridgeNode: NodeDefinition = {
    type: 'automation-starbridge', category: 'crm-sales', label: 'Starbridge',
    description: 'Find public-sector buyers, research opportunities, manage bridge row statuses and monitor new or updated rows',
    Icon: StarbridgeIcon, iconColor: '', dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={StarbridgeIcon} iconColor="" />),
};
