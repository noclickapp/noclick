import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const BasinIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/basin.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const BasinNode: NodeDefinition = {
    type: 'automation-basin', category: 'forms', label: 'Basin',
    description: 'Manage forms, submissions, projects and webhooks',
    Icon: BasinIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={BasinIcon} iconColor="" />),
};
