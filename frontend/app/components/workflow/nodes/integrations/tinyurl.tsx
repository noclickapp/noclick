import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const TinyURLIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/tinyurl.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const TinyURLNode: NodeDefinition = {
    type: 'automation-tinyurl', category: 'marketing', label: 'TinyURL',
    description: 'Shorten and manage links, track clicks, and read traffic analytics',
    keywords: ['url shortener', 'short links', 'branded links', 'click analytics'],
    Icon: TinyURLIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={TinyURLIcon} iconColor="" />),
};
