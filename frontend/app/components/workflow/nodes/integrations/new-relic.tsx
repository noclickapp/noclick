import { memo } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition } from '~/components/workflow/nodes/types';


import type { CSSProperties as BrandCSSProperties } from 'react';
import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
// Vector brand artwork from https://newrelic.com/
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <ThemedBrandImg light="/icons/new-relic-brand-vector.svg" dark="/icons/new-relic-brand-vector-dark.svg" className={className} style={style} />
);

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const NewRelicNodeComponent = (props: NodeProps) => (
    <AutomationNode {...props} Icon={OfficialBrandIcon} iconColor="" />
);

export const NewRelicNode: NodeDefinition = {
    type: 'automation-new-relic',
    label: 'New Relic',
    description: 'Query telemetry and manage alerts in New Relic',
    category: 'monitoring',
    Icon: OfficialBrandIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(NewRelicNodeComponent),
};
