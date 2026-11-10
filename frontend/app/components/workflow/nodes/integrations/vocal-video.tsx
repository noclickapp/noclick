// Registers Vocal Video in the workflow canvas and integration catalog.
// The media category and official icon make the new workspace tools discoverable.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const VocalVideoIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/vocal-video.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const VocalVideoNode: NodeDefinition = {
    type: 'automation-vocal-video', category: 'media', label: 'Vocal Video',
    description: 'Collect video testimonials, manage replies, galleries and storyboards',
    keywords: ['testimonial', 'video request', 'customer story', 'Vocal Video'],
    Icon: VocalVideoIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={VocalVideoIcon} iconColor="" />),
};
