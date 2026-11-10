import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const OwnerRezIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/ownerrez.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const OwnerRezNode: NodeDefinition = {
    type: 'automation-ownerrez', category: 'bookings', label: 'OwnerRez',
    description: 'Manage vacation rental bookings, guests, quotes, availability and tags',
    Icon: OwnerRezIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={OwnerRezIcon} iconColor="" />),
};
