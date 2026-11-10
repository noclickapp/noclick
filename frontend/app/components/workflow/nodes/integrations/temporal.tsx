import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const TemporalIcon = ({
    className,
    style,
}: {
    className?: string;
    style?: CSSProperties;
}) => (
    <>
        <img
            src="/icons/temporal.svg"
            alt=""
            aria-hidden="true"
            className={`${className ?? ''} dark:hidden`}
            style={{ ...style, objectFit: 'contain' } as CSSProperties}
        />
        <img
            src="/icons/temporal-dark.svg"
            alt=""
            aria-hidden="true"
            className={`${className ?? ''} hidden dark:block`}
            style={{ ...style, objectFit: 'contain' } as CSSProperties}
        />
    </>
);

export const TemporalNode: NodeDefinition = {
    type: 'automation-temporal',
    category: 'developer-tools',
    label: 'Temporal',
    description:
        'Manage Temporal Cloud namespaces, users, service accounts and access; inspect provisioning status',
    keywords: ['Temporal Cloud', 'Cloud Ops', 'namespace', 'orchestration'],
    Icon: TemporalIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo(function TemporalComponent(props: NodeProps) {
        return <AutomationNode {...props} Icon={TemporalIcon} iconColor="" />;
    }),
};
