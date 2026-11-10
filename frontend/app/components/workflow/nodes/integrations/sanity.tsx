// Sanity Content Lake node definition for the FlowCanvas.
// The icon and schema connect the API token workflow to the shared automation editor.

import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition } from '~/components/workflow/nodes/types';


// Unmodified compact brand asset from https://www.sanity.io
import type { CSSProperties as BrandCSSProperties } from 'react';
import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <ThemedBrandImg light="/icons/sanity-brand.svg" dark="/icons/sanity-brand-dark.svg" className={className} style={style} />
);

const SanityNodeComponent = (props: NodeProps) => <AutomationNode {...props} Icon={OfficialBrandIcon} iconColor="" />;

export const SanityNode: NodeDefinition = {
    type: 'automation-sanity',
    label: 'Sanity',
    description: 'Query and manage Sanity Content Lake',
    category: 'content-research',
    Icon: OfficialBrandIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: SanityNodeComponent,
};
