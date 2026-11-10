import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';
const Icon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/alttext-ai.svg" alt="" aria-hidden="true" className={className} style={{ ...style, objectFit: 'contain' }} />
);
export const AlttextAiNode: NodeDefinition = {
    type: 'automation-alttext-ai', category: 'ai', label: 'AltText.ai',
    description: 'Generate and manage image alt text, scrape pages and read account usage',
    keywords: ['Alttext Ai', 'accessibility', 'SEO'], Icon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={Icon} iconColor="" />),
};
