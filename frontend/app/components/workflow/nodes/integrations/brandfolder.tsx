// Brandfolder's definition makes the integration discoverable in the canvas and catalog.
// The official brand icon identifies asset operations and asset-event triggers.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const BrandfolderIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/brandfolder.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const BrandfolderNode: NodeDefinition = {
    type: 'automation-brandfolder', category: 'media', label: 'Brandfolder',
    description: 'Manage digital assets, collections, sections, tags and labels; react to asset events',
    keywords: ['digital asset management', 'DAM', 'Smartsheet', 'brand assets'],
    Icon: BrandfolderIcon, iconColor: '', dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={BrandfolderIcon} iconColor="" />),
};
