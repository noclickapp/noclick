// Housecall Pro provides customer, job and sales automation for field service businesses.
// This definition exposes its generated operation schema in the workflow catalog.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const HousecallProIcon = ({
    className,
    style,
}: {
    className?: string;
    style?: CSSProperties;
}) => (
    <img
        src="/icons/housecall-pro.svg"
        alt=""
        aria-hidden="true"
        className={className}
        style={
            {
                ...style,
                '--brand-invert': 0,
                objectFit: 'contain',
            } as CSSProperties
        }
    />
);

export const HousecallProNode: NodeDefinition = {
    type: 'automation-housecall-pro',
    category: 'industry',
    label: 'Housecall Pro',
    description:
        'Manage customers, jobs, appointments, line items, leads and estimates',
    keywords: ['field service', 'home services', 'contractor', 'Housecall'],
    Icon: HousecallProIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo(function HousecallProAutomation(props: NodeProps) {
        return (
            <AutomationNode {...props} Icon={HousecallProIcon} iconColor="" />
        );
    }),
};
