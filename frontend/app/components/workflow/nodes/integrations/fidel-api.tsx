import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const FidelAPIIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/fidel-api.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const FidelAPINode: NodeDefinition = {
    type: 'automation-fidel-api', category: 'finance-accounting', label: 'Fidel Api',
    description: 'Manage brands, programs, offers and webhooks; read transactions',
    Icon: FidelAPIIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={FidelAPIIcon} iconColor="" />),
};
