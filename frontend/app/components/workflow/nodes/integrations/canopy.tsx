import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const CanopyIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <>
        <img src="/icons/canopy.svg" alt="" aria-hidden="true" className={`${className ?? ''} dark:hidden`}
            style={{ ...style, objectFit: 'contain' } as CSSProperties} />
        <img src="/icons/canopy-dark.svg" alt="" aria-hidden="true" className={`${className ?? ''} hidden dark:block`}
            style={{ ...style, objectFit: 'contain' } as CSSProperties} />
    </>
);

export const CanopyNode: NodeDefinition = {
    type: 'automation-canopy', category: 'finance-accounting', label: 'Canopy',
    description: 'Manage accounting clients, contacts, notes and tasks',
    keywords: ['accounting', 'tax', 'practice management', 'CRM'],
    Icon: CanopyIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={CanopyIcon} iconColor="" />),
};
