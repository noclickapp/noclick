import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const DiscourseIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/discourse-brand-vector.svg" dark="/icons/discourse-brand-vector-dark.svg" className={className} style={style} />
);

const DiscourseNodeComponent = (props: NodeProps) => (
    <AutomationNode {...props} Icon={DiscourseIcon} iconColor="" />
);

export const DiscourseNode: NodeDefinition = {
    type: 'automation-discourse',
    label: 'Discourse',
    description: 'Discourse community/forum automation',
    Icon: DiscourseIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: DiscourseNodeComponent,
};
