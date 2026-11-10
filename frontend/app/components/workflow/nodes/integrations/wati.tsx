import { memo } from 'react';
import type { CSSProperties } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const WATIIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/wati.svg" dark="/icons/wati-dark.svg" className={className} style={style} />
);
const WATINodeComponent = (props: NodeProps) => <AutomationNode {...props} Icon={WATIIcon} iconColor="" />;
export const WATINode: NodeDefinition = {
    type: 'automation-wati', category: 'communication', label: 'WATI',
    description: 'WATI V3 contacts and protected service metadata',
    Icon: WATIIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo(WATINodeComponent),
};
