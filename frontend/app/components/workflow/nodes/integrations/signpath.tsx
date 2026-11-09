import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const SignpathIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/signpath.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const SignpathNode: NodeDefinition = {
    type: 'automation-signpath', category: 'developer-tools', label: 'SignPath',
    description: 'Automate code signing requests, artifacts, projects and certificates',
    Icon: SignpathIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={SignpathIcon} iconColor="" />),
};
