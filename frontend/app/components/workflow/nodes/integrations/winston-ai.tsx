import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const WinstonAIIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <>
        <img src="/icons/winston-ai.svg" alt="" aria-hidden="true" className={`${className ?? ''} dark:hidden`}
            style={{ ...style, objectFit: 'contain' }} />
        <img src="/icons/winston-ai-dark.svg" alt="" aria-hidden="true" className={`${className ?? ''} hidden dark:block`}
            style={{ ...style, objectFit: 'contain' }} />
    </>
);

export const WinstonAINode: NodeDefinition = {
    type: 'automation-winston-ai', category: 'ai', label: 'Winston AI',
    description: 'Detect AI content and images, check plagiarism and facts, and compare texts',
    keywords: ['winston', 'AI detection', 'plagiarism', 'fact checker', 'forensics'],
    Icon: WinstonAIIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={WinstonAIIcon} iconColor="" />),
};
