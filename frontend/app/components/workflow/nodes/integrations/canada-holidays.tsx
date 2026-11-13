import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const CanadaHolidaysIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/canada-holidays.svg" className={className} style={style} />
);

export const CanadaHolidaysNode: NodeDefinition = {
    type: 'automation-canada-holidays', category: 'content-research', label: 'Canada Holidays API',
    description: 'Look up Canadian federal, provincial and optional holidays without an account',
    keywords: ['statutory holidays', 'Canada', 'province', 'territory', 'public holidays'],
    Icon: CanadaHolidaysIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={CanadaHolidaysIcon} iconColor="" />),
};
