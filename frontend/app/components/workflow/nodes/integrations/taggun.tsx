// Taggun's self-discovered canvas and integration catalog definition.
// It uses the official provider mark and groups receipt automation under finance.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const TaggunIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/taggun.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const TaggunNode: NodeDefinition = {
    type: 'automation-taggun', category: 'finance-accounting', label: 'Taggun',
    description: 'Extract and validate receipts, train merchant recognition, and manage campaign rules',
    keywords: ['receipt', 'OCR', 'expense', 'invoice', 'validation'],
    Icon: TaggunIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={TaggunIcon} iconColor="" />),
};
