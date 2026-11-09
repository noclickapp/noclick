// Olostep's own definition exposes its generated operation schema in the canvas.
// Discovery loads this file without adding shared registry entries.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const OlostepIcon = ({
    className,
    style,
}: {
    className?: string;
    style?: CSSProperties;
}) => (
    <img
        src="/icons/olostep.svg"
        alt=""
        aria-hidden="true"
        className={className}
        style={{ ...style, objectFit: 'contain' } as CSSProperties}
    />
);

export const OlostepNode: NodeDefinition = {
    type: 'automation-olostep',
    category: 'content-research',
    label: 'Olostep',
    description:
        'Scrape pages, crawl websites, search, research and schedule API jobs',
    Icon: OlostepIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo(function OlostepCanvas(props: NodeProps) {
        return <AutomationNode {...props} Icon={OlostepIcon} iconColor="" />;
    }),
};
