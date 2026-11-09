// Convolo Ai uses the Brightcall Dialer external API for projects, contacts and AI agents.
// This definition makes the integration discoverable in the canvas and public catalog.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const ConvoloAiIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/convolo-ai.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const ConvoloAiNode: NodeDefinition = {
    type: 'automation-convolo-ai', category: 'ai', label: 'Convolo Ai',
    description: 'Manage Brightcall projects, contacts, AI agents and call history',
    keywords: ['Brightcall', 'Convolo', 'dialer', 'voice', 'calls', 'contacts'],
    Icon: ConvoloAiIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={ConvoloAiIcon} iconColor="" />),
};
