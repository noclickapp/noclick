import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const TripadvisorIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/tripadvisor.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const TripadvisorNode: NodeDefinition = {
    type: 'automation-tripadvisor', category: 'content-research', label: 'Tripadvisor',
    description: 'Start workflows from new reviews, search travel locations, read photos, manage allowlists and inspect data feeds',
    Icon: TripadvisorIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={TripadvisorIcon} iconColor="" />),
};
