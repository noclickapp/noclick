import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const PomaGrillIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/poma-grill.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const PomaGrillNode: NodeDefinition = {
    type: 'automation-poma-grill', category: 'ai', label: 'Poma Grill',
    description: 'Ingest documents, search RAG context, and manage Grill documents, projects and jobs',
    Icon: PomaGrillIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={PomaGrillIcon} iconColor="" />),
};
