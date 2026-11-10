import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const GoogleCloudNaturalLanguageIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/google-cloud-natural-language.svg" alt="" aria-hidden="true" className={className} style={{ ...style, objectFit: 'contain' }} />
);

export const GoogleCloudNaturalLanguageNode: NodeDefinition = {
    type: 'automation-google-cloud-natural-language',
    category: 'ai',
    label: 'Google Cloud Natural Language',
    description: 'Analyze sentiment, entities, syntax, categories and content safety in text or Cloud Storage documents',
    keywords: ['NLP', 'text analysis', 'Google NLP', 'sentiment analysis'],
    Icon: GoogleCloudNaturalLanguageIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={GoogleCloudNaturalLanguageIcon} iconColor="" />),
};
