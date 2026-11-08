import { memo } from 'react';
import type { CSSProperties } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition } from '~/components/workflow/nodes/types';

const NutshellIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/nutshell-brand-vector.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

const NutshellNodeComponent = (props: NodeProps) => (
    <AutomationNode {...props} Icon={NutshellIcon} iconColor="" />
);

export const NutshellNode: NodeDefinition = {
    type: 'automation-nutshell',
    label: 'Nutshell',
    description: 'Nutshell CRM automation',
    category: 'crm-sales',
    Icon: NutshellIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo(NutshellNodeComponent),
};
