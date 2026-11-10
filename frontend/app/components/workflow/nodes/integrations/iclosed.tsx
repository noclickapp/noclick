// iClosed exposes account CRM and scheduling operations through its v1 API.
// This definition makes the self-registering node available in the canvas and catalog.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const IClosedIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <>
        <img src="/icons/iclosed.svg" alt="" aria-hidden="true" className={`${className ?? ''} dark:hidden`}
            style={{ ...style, objectFit: 'contain' }} />
        <img src="/icons/iclosed-dark.svg" alt="" aria-hidden="true" className={`${className ?? ''} hidden dark:block`}
            style={{ ...style, objectFit: 'contain' }} />
    </>
);

export const IClosedNode: NodeDefinition = {
    type: 'automation-iclosed', category: 'bookings', label: 'iClosed',
    description: 'Manage contacts, notes, deals, calls, events, products and transactions',
    keywords: ['sales', 'booking', 'scheduling', 'CRM', 'iClosed.io'],
    Icon: IClosedIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={IClosedIcon} iconColor="" />),
};
