import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';
import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';

const KapsoIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/kapso.svg" dark="/icons/kapso-dark.svg" className={className} style={{ ...style, objectFit: 'contain' }} />
);

export const KapsoNode: NodeDefinition = {
    type: 'automation-kapso', category: 'communication', label: 'Kapso',
    description: 'Send WhatsApp messages and manage conversations, contacts, templates and business profiles',
    Icon: KapsoIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={KapsoIcon} iconColor="" />),
};
