// Connect W&B Weave operations to the workflow canvas and integration catalog.
// Configuration and credential forms come from the backend-generated schema.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const WeightsAndBiasesIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/weights-and-biases.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const WeightsAndBiasesNode: NodeDefinition = {
    type: 'automation-weights-and-biases', category: 'ai', label: 'Weights And Biases',
    description: 'Query Weave traces, publish objects and tables, and automate feedback and costs',
    Icon: WeightsAndBiasesIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={WeightsAndBiasesIcon} iconColor="" />),
};
