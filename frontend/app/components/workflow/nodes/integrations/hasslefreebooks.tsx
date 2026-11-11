import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const HassleFreeBooksIcon = ({
    className,
    style,
}: {
    className?: string;
    style?: CSSProperties;
}) => (
    <img
        src="/icons/hasslefreebooks.svg"
        alt=""
        aria-hidden="true"
        className={className}
        style={{ ...style, objectFit: 'contain' }}
    />
);

export const HassleFreeBooksNode: NodeDefinition = {
    type: 'automation-hasslefreebooks',
    category: 'finance-accounting',
    label: 'HassleFreeBooks',
    description:
        'Automate contacts, invoices, bills, journal entries and financial reports',
    keywords: ['bookkeeping', 'accounting', 'payments', 'Hassle Free Books'],
    Icon: HassleFreeBooksIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo(function HassleFreeBooksComponent(props: NodeProps) {
        return (
            <AutomationNode
                {...props}
                Icon={HassleFreeBooksIcon}
                iconColor=""
            />
        );
    }),
};
