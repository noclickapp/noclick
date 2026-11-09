// Simpro field service operations use the shared schema-driven editor.
// This definition provides the catalog category and official provider icon.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const SimproIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/simpro.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const SimproNode: NodeDefinition = {
    type: 'automation-simpro', category: 'industry', label: 'Simpro',
    description: 'Manage field service customers, contacts, sites, jobs, quotes and invoices',
    Icon: SimproIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={SimproIcon} iconColor="" />),
};
