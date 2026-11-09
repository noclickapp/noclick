import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const MagicHourIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/magic-hour.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const MagicHourNode: NodeDefinition = {
    type: 'automation-magic-hour', category: 'ai', label: 'Magic Hour',
    description: 'Generate and edit AI images, videos and audio, and manage media projects',
    keywords: ['magic hour', 'text to video', 'image generation', 'lip sync', 'speech', 'music'],
    Icon: MagicHourIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={MagicHourIcon} iconColor="" />),
};
