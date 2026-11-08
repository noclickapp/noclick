import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const DiscourseIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/discourse-brand-vector.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
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
