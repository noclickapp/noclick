// Parsera joins the self-discovered integration catalog and workflow canvas.
// Its official brand icon identifies API-key extraction and scraper operations.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const ParseraIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/parsera.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const ParseraNode: NodeDefinition = {
    type: 'automation-parsera', category: 'content-research', label: 'Parsera',
    description: 'Extract structured web data, build scrapers and manage extraction runs',
    Icon: ParseraIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={ParseraIcon} iconColor="" />),
};
