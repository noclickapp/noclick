import { memo } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';


import type { CSSProperties as BrandCSSProperties } from 'react';
// Vector brand artwork from https://baserow.io
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <img src="/icons/baserow-brand-vector.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const BaserowNode: NodeDefinition = {
    type: 'automation-baserow',
    label: 'Baserow',
    description: 'Read and write Baserow database rows',
    category: 'databases-storage',
    Icon: OfficialBrandIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => (
        <AutomationNode {...props} Icon={OfficialBrandIcon} iconColor="" />
    )),
};
