import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';
import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';

// Unmodified current Personio wordmark published in its official Developer Hub.
const PersonioIcon = ({
    className,
    style,
}: {
    className?: string;
    style?: CSSProperties;
}) => (
    <ThemedBrandImg light="/icons/personio-brand.svg" dark="/icons/personio-brand-dark.svg" className={className} style={{ ...style, objectFit: 'contain' }} />
);

export const PersonioNode: NodeDefinition = {
    type: 'automation-personio',
    label: 'Personio',
    description: 'Sync employees, time off and attendance with Personio',
    category: 'hr-recruiting',
    keywords: [
        'HR',
        'HRIS',
        'employees',
        'time off',
        'absence balances',
        'attendance',
    ],
    Icon: PersonioIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => (
        <AutomationNode {...props} Icon={PersonioIcon} iconColor="" />
    )),
};
