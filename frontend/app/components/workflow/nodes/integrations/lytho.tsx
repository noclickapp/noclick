// Lytho DAM exposes tenant assets, collections and tags in the workflow catalog.
// This definition lets discovery load its canvas component and integration category.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const LythoIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/lytho.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const LythoNode: NodeDefinition = {
    type: 'automation-lytho', category: 'media', label: 'Lytho',
    description: 'Automate DAM assets, collections and tags; watch for new and updated assets',
    keywords: ['DAM', 'digital asset management', 'brand', 'media'],
    Icon: LythoIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={LythoIcon} iconColor="" />),
};
