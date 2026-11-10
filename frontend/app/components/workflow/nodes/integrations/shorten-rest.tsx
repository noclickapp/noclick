// Registers Shorten Rest in the workflow canvas and integration catalog.
// Its schema and credentials are generated from the backend node.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const ShortenRestIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/shorten-rest.jpg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const ShortenRestNode: NodeDefinition = {
    type: 'automation-shorten-rest', category: 'marketing', label: 'Shorten Rest',
    description: 'Shorten links, manage destinations and tracking, and retrieve clicks',
    keywords: ['shorten.rest', 'short URL', 'short links', 'short.fyi'],
    Icon: ShortenRestIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={ShortenRestIcon} iconColor="" />),
};
