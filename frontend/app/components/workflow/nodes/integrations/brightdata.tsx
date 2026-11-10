import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const BrightdataIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/brightdata.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const BrightdataNode: NodeDefinition = {
    type: 'automation-brightdata', category: 'content-research', label: 'Bright Data',
    description: 'Search engines, run scrapers, and manage dataset snapshots',
    Icon: BrightdataIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={BrightdataIcon} iconColor="" />),
};
