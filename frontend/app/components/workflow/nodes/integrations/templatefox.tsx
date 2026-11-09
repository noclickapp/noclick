import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const TemplatefoxIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/templatefox.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const TemplatefoxNode: NodeDefinition = {
    type: 'automation-templatefox', category: 'documents', label: 'TemplateFox',
    description: 'Generate PDFs and images, manage template versions and check usage',
    Icon: TemplatefoxIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={TemplatefoxIcon} iconColor="" />),
};
