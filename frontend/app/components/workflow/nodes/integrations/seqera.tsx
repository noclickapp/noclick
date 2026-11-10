import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const SeqeraIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/seqera.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const SeqeraNode: NodeDefinition = {
    type: 'automation-seqera', category: 'developer-tools', label: 'Seqera',
    description: 'Launch and monitor Nextflow workflows, manage pipelines and datasets',
    Icon: SeqeraIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={SeqeraIcon} iconColor="" />),
};
