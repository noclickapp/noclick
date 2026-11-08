import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const SendsparkIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/sendspark.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' } as CSSProperties} />
);

export const SendsparkNode: NodeDefinition = {
    type: 'automation-sendspark', label: 'Sendspark',
    category: 'media',
    description: 'Personalized video campaigns, prospects, webhooks and transcripts',
    keywords: ['video outreach', 'dynamic video', 'personalized video'],
    Icon: SendsparkIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={SendsparkIcon} iconColor="" />),
};
