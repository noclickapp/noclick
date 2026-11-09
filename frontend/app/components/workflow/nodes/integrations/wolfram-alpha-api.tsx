// Wolfram Alpha API brings computational knowledge into workflows.
// This definition discovers the node with the official provider icon.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const WolframAlphaApiIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/wolfram-alpha-api.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const WolframAlphaApiNode: NodeDefinition = {
    type: 'automation-wolfram-alpha-api', category: 'content-research', label: 'Wolfram Alpha API',
    description: 'Query knowledge, solve equations, calculate, and convert units, currencies and dates',
    Icon: WolframAlphaApiIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={WolframAlphaApiIcon} iconColor="" />),
};
