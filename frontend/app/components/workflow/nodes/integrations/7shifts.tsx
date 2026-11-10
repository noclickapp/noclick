import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const SevenShiftsIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/7shifts.svg" dark="/icons/7shifts-dark.svg" className={className} style={style} />
);

export const SevenShiftsNode: NodeDefinition = {
    type: 'automation-7shifts', label: '7shifts',
    category: 'hr-recruiting',
    description: 'Automate employees, shifts, time punches and time off',
    keywords: ['scheduling', 'employees', 'time clock', 'workforce', 'payroll'],
    Icon: SevenShiftsIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={SevenShiftsIcon} iconColor="" />),
};
