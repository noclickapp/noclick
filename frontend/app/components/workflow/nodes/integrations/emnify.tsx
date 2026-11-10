import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const EMnifyIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/emnify.svg" dark="/icons/emnify-dark.svg" className={className} style={style} />
);

export const EMnifyNode: NodeDefinition = {
    type: 'automation-emnify', category: 'industry', label: 'EMnify',
    description: 'Manage IoT endpoints, SIMs, SMS, quotas and connectivity',
    Icon: EMnifyIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={EMnifyIcon} iconColor="" />),
};
