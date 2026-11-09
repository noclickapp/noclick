// Senta catalog and canvas definition, discovered without a shared registry.
// Uses the publisher icon and groups practice automation under accounting.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const SentaIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/senta.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' } as CSSProperties} />
);

export const SentaNode: NodeDefinition = {
    type: 'automation-senta', category: 'finance-accounting', label: 'Senta',
    description: 'Manage practice clients, search records, list jobs and add notes',
    keywords: ['accounting', 'practice management', 'IRIS', 'clients', 'jobs'],
    Icon: SentaIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={SentaIcon} iconColor="" />),
};
