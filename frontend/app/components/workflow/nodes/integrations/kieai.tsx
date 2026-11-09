import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const KieaiIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/kieai.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const KieaiNode: NodeDefinition = {
    type: 'automation-kieai', category: 'ai', label: 'Kieai',
    description: 'Run AI chats, transcribe audio, create characters and get file links',
    Icon: KieaiIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={KieaiIcon} iconColor="" />),
};
