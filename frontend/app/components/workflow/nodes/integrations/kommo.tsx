import { memo, type CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const KommoIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/kommo.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);
const KommoNodeComponent = (props: NodeProps) => (
    <AutomationNode {...props} Icon={KommoIcon} iconColor="" />
);

export const KommoNode: NodeDefinition = {
    type: 'automation-kommo',
    label: 'Kommo',
    description: 'Kommo CRM automation',
    Icon: KommoIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo(KommoNodeComponent),
};
