import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const BrowseaiIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <>
        <img src="/icons/browseai.svg" alt="" aria-hidden="true" className={`${className ?? ''} dark:hidden`}
            style={{ ...style, objectFit: 'contain' } as CSSProperties} />
        <img src="/icons/browseai-dark.svg" alt="" aria-hidden="true" className={`${className ?? ''} hidden dark:block`}
            style={{ ...style, objectFit: 'contain' } as CSSProperties} />
    </>
);

export const BrowseaiNode: NodeDefinition = {
    type: 'automation-browseai', category: 'content-research', label: 'Browse AI',
    description: 'Run extraction robots, manage monitors and respond to scraped data changes',
    Icon: BrowseaiIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={BrowseaiIcon} iconColor="" />),
};
