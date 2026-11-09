// PreciseFP adds account, contact and financial profile actions to the workflow catalog.
// The publisher's symbol identifies the service; its source and hash are recorded beside the asset.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const PreciseFPIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/precisefp.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' } as CSSProperties} />
);

export const PreciseFPNode: NodeDefinition = {
    type: 'automation-precisefp', category: 'finance-accounting', label: 'PreciseFP',
    description: 'Manage client accounts and contacts; read financial profiles, goals and documents',
    keywords: ['financial planning', 'client intake', 'prospects'],
    Icon: PreciseFPIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={PreciseFPIcon} iconColor="" />),
};
