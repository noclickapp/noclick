import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const PersonaIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/persona.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const PersonaNode: NodeDefinition = {
    type: 'automation-persona', category: 'industry', label: 'Persona',
    description: 'Manage identity verification inquiries, accounts, cases and reports',
    keywords: ['identity', 'verification', 'KYC', 'compliance'],
    Icon: PersonaIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={PersonaIcon} iconColor="" />),
};
