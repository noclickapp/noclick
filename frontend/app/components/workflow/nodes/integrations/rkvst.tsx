// Rkvst (now DataTrails) workflow node and integration catalog entry.
// The provider icon and schema are owned by this integration.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const RkvstIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/rkvst.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const RkvstNode: NodeDefinition = {
    type: 'automation-rkvst', category: 'developer-tools', label: 'Rkvst', keywords: ['DataTrails', 'provenance', 'evidence'],
    description: 'Track asset provenance, record evidence events and manage locations',
    Icon: RkvstIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={RkvstIcon} iconColor="" />),
};
