// Quiltt catalog and canvas definition. Uses the official service icon to identify this integration.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const QuilttIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/quiltt.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const QuilttNode: NodeDefinition = {
    type: 'automation-quiltt', category: 'finance-accounting', label: 'Quiltt',
    description: 'Manage financial profiles, connection imports, refreshes and webhooks',
    Icon: QuilttIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={QuilttIcon} iconColor="" />),
};
