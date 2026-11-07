import type { CSSProperties as BrandCSSProperties } from 'react';
import { memo } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition } from '~/components/workflow/nodes/types';

// Sourced brand artwork: https://www.algolia.com/files/live/sites/algolia-assets/files/icons/algolia-logo-for-favicon.svg
const PreferredBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <img src="/icons/algolia-preferred-brand.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as BrandCSSProperties} />
);

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const AlgoliaNodeComponent = (props: NodeProps) => (
    <AutomationNode {...props} Icon={PreferredBrandIcon} iconColor="text-blue-500" />
);

export const AlgoliaNode: NodeDefinition = {
    type: 'automation-algolia',
    label: 'Algolia',
    description: 'Search, indexing, analytics, insights, and ingestion',
    Icon: PreferredBrandIcon,
    iconColor: 'text-blue-500',
    dimensions: DIMENSIONS,
    component: memo(AlgoliaNodeComponent),
};
