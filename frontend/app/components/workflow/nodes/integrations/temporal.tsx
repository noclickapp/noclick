import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const TemporalIcon = ({
    className,
    style,
}: {
    className?: string;
    style?: CSSProperties;
}) => (
    <ThemedBrandImg light="/icons/temporal.svg" dark="/icons/temporal-dark.svg" className={className} style={style} />
);

export const TemporalNode: NodeDefinition = {
    type: 'automation-temporal',
    category: 'developer-tools',
    label: 'Temporal',
    description:
        'Manage Temporal Cloud namespaces, users, service accounts and access; inspect provisioning status and trigger on new Cloud audit logs',
    keywords: ['Temporal Cloud', 'Cloud Ops', 'namespace', 'orchestration', 'audit log', 'trigger'],
    Icon: TemporalIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo(function TemporalComponent(props: NodeProps) {
        return <AutomationNode {...props} Icon={TemporalIcon} iconColor="" />;
    }),
};
