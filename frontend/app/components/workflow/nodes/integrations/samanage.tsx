import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const SamanageIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/samanage.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const SamanageNode: NodeDefinition = {
    type: 'automation-samanage', category: 'support', label: 'SolarWinds Service Desk', keywords: ['Samanage', 'ITSM', 'help desk'],
    description: 'Manage incidents, users, solutions, problems and changes',
    Icon: SamanageIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={SamanageIcon} iconColor="" />),
};
