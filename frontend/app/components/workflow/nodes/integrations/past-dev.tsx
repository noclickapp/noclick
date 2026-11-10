import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const PastDevIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/past-dev.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const PastDevNode: NodeDefinition = {
    type: 'automation-past-dev', category: 'ai', label: 'Past Dev',
    description: 'Ingest and recall memory, manage identities and audiences, and inspect ingestion and usage',
    keywords: ['past.dev', 'memory', 'recall', 'identities', 'audiences'],
    Icon: PastDevIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={PastDevIcon} iconColor="" />),
};
