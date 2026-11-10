import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const BookwhenIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/bookwhen.svg" dark="/icons/bookwhen-dark.svg" className={className} style={style} />
);

export const BookwhenNode: NodeDefinition = {
    type: 'automation-bookwhen', category: 'bookings', label: 'Bookwhen',
    description: 'Read events, tickets, locations, attachments and class passes',
    Icon: BookwhenIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={BookwhenIcon} iconColor="" />),
};
