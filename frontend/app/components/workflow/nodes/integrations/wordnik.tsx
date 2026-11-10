import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const WordnikIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/wordnik.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const WordnikNode: NodeDefinition = {
    type: 'automation-wordnik', category: 'content-research', label: 'Wordnik',
    description: 'Look up definitions, examples, related words, pronunciations and the word of the day',
    Icon: WordnikIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={WordnikIcon} iconColor="" />),
};
