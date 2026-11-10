import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const WacheteIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/wachete.svg" dark="/icons/wachete-dark.svg" className={className} style={style} />
);

export const WacheteNode: NodeDefinition = {
    type: 'automation-wachete', category: 'content-research', label: 'Wachete',
    description: 'Monitor pages and manage folders, change history and notifications',
    Icon: WacheteIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={WacheteIcon} iconColor="" />),
};
