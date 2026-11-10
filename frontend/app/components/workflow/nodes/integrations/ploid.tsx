import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const PloidIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/ploid.svg" dark="/icons/ploid-dark.svg" className={className} style={style} />
);

export const PloidNode: NodeDefinition = {
    type: 'automation-ploid', category: 'hr-recruiting', label: 'Ploid',
    description: 'Search and enrich people, automate monitors and research datasets',
    Icon: PloidIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={PloidIcon} iconColor="" />),
};
