import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

// Official brand artwork from https://deepgram.com/.
const DeepgramIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/deepgram-brand-vector.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

const DeepgramNodeComponent = (props: NodeProps) => <AutomationNode {...props} Icon={DeepgramIcon} iconColor="" />;

export const DeepgramNode: NodeDefinition = {
    type: 'automation-deepgram',
    label: 'Deepgram',
    description: 'Transcribe audio, generate speech, analyze text, and inspect projects',
    category: 'ai',
    Icon: DeepgramIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: DeepgramNodeComponent,
};
