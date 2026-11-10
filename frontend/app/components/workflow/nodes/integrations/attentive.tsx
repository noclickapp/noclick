import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const AttentiveIcon = ({
    className,
    style,
}: {
    className?: string;
    style?: CSSProperties;
}) => (
    <ThemedBrandImg light="/icons/attentive.svg" dark="/icons/attentive-dark.svg" className={className} style={style} />
);

export const AttentiveNode: NodeDefinition = {
    type: 'automation-attentive',
    category: 'marketing',
    label: 'Attentive',
    description:
        'Manage SMS and email subscribers, segments, custom attributes and ecommerce events',
    keywords: ['sms', 'email', 'subscribers', 'marketing', 'ecommerce'],
    Icon: AttentiveIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo(function AttentiveComponent(props: NodeProps) {
        return <AutomationNode {...props} Icon={AttentiveIcon} iconColor="" />;
    }),
};
