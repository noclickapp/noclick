import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const EduzzIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/eduzz.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain', '--brand-invert': 0 } as CSSProperties} />
);

export const EduzzNode: NodeDefinition = {
    type: 'automation-eduzz',
    category: 'courses',
    label: 'Eduzz',
    description: 'Automate sales, subscriptions, customers and students, with signed invoice and subscription events',
    keywords: ['MyEduzz', 'Nutror', 'AlpaClass', 'courses', 'invoices'],
    Icon: EduzzIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={EduzzIcon} iconColor="" />),
};
