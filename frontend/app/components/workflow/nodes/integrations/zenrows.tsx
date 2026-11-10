import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const ZenrowsIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/zenrows.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const ZenrowsNode: NodeDefinition = {
    type: 'automation-zenrows', label: 'ZenRows',
    category: 'content-research',
    description: 'Submit scraping jobs, manage runs and schedules, and read results',
    keywords: ['zenrows', 'scraping', 'batch', 'crawler', 'web scraping'],
    Icon: ZenrowsIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={ZenrowsIcon} iconColor="" />),
};
