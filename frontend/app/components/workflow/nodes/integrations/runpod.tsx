import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const RunpodIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/runpod.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const RunpodNode: NodeDefinition = {
    type: 'automation-runpod', category: 'cloud-hosting', label: 'Runpod',
    description: 'Manage Pods, Serverless endpoints, templates and network volumes',
    Icon: RunpodIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={RunpodIcon} iconColor="" />),
};
