import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const ZeplinIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/zeplin.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const ZeplinNode: NodeDefinition = {
    type: 'automation-zeplin', category: 'developer-tools', label: 'Zeplin',
    description: 'Automate design handoff with projects, screens, notes, comments and styleguides',
    Icon: ZeplinIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={ZeplinIcon} iconColor="" />),
};
