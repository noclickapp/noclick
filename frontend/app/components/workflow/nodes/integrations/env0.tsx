// env zero reads scoped organization, project, environment and deployment metadata.
// The canvas definition is discovered alongside env0 metadata.
import { memo } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';
import type { CSSProperties as BrandCSSProperties } from 'react';
import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
// Vector brand artwork from https://www.env0.com/
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <ThemedBrandImg light="/icons/env0-brand-vector.svg" dark="/icons/env0-brand-vector-dark.svg" className={className} style={style} />
);

export const Env0Node: NodeDefinition = {
    type: 'automation-env0', category: 'cloud-hosting', label: 'env zero',
    description: 'Read scoped infrastructure deployment metadata',
    keywords: ['env0', 'env zero', 'projects', 'environments', 'deployments'],
    Icon: OfficialBrandIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={OfficialBrandIcon} iconColor="" />),
};
