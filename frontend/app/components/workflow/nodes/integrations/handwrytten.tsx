// Defines Handwrytten in the workflow catalog and canvas.
// The schema comes from the backend's v1 operation models and credential metadata.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const HandwryttenIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/handwrytten.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const HandwryttenNode: NodeDefinition = {
    type: 'automation-handwrytten', label: 'Handwrytten',
    description: 'Send handwritten cards and manage recipients, templates and custom card designs with the v1 API',
    keywords: ['handwritten', 'thank you', 'direct mail', 'greeting cards'],
    Icon: HandwryttenIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={HandwryttenIcon} iconColor="" />),
};
