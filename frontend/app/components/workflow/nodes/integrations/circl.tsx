// Adds CIRCL hashlookup to the workflow canvas and integration catalog.
// The public API needs no account; sessions require a server with that feature enabled.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const CirclIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/circl.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const CirclNode: NodeDefinition = {
    type: 'automation-circl', category: 'developer-tools', label: 'hashlookup CIRCL API',
    description: 'Look up known file hashes, query batches and explore file relationships',
    keywords: ['hashlookup', 'CIRCL', 'security', 'forensics', 'MD5', 'SHA1', 'SHA256', 'NSRL'],
    Icon: CirclIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={CirclIcon} iconColor="" />),
};
