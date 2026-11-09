import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const JigsawstackIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/jigsawstack.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' } as CSSProperties} />
);

export const JigsawstackNode: NodeDefinition = {
    type: 'automation-jigsawstack', category: 'ai', label: 'JigsawStack',
    description: 'Analyze, translate and extract content, search the web and manage saved prompts',
    Icon: JigsawstackIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={JigsawstackIcon} iconColor="" />),
};
