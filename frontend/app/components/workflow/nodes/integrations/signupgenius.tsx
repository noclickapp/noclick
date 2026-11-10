import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const SignUpGeniusIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/signupgenius.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const SignUpGeniusNode: NodeDefinition = {
    type: 'automation-signupgenius', category: 'nonprofit', label: 'SignUpGenius',
    description: 'Manage volunteer groups, participants, sign ups and slot reports',
    Icon: SignUpGeniusIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={SignUpGeniusIcon} iconColor="" />),
};
