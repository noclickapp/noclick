import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const KontentAiIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/kontent-ai.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const KontentAiNode: NodeDefinition = {
    type: 'automation-kontent-ai', category: 'content-research', label: 'Kontent.ai',
    description: 'Manage content items, publishing, assets, languages and taxonomies',
    keywords: ['kontent', 'kontent ai', 'cms', 'headless cms'],
    Icon: KontentAiIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={KontentAiIcon} iconColor="" />),
};
