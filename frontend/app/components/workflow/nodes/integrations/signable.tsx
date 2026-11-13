import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';
import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';

const SignableIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/signable.svg" dark="/icons/signable-dark.svg" className={className} style={style} />
);

export const SignableNode: NodeDefinition = {
    type: 'automation-signable', category: 'documents', label: 'Signable',
    description: 'Start workflows from Signable events, send envelopes, and manage contacts and templates',
    Icon: SignableIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={SignableIcon} iconColor="" />),
};
