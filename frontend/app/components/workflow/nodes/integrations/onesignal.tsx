import { memo } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition } from '~/components/workflow/nodes/types';


import type { CSSProperties as BrandCSSProperties } from 'react';
// Vector brand artwork from https://onesignal.com
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <img src="/icons/onesignal-brand-vector.svg" alt="" aria-hidden="true" className={(className || '') + ' [--brand-invert:0] dark:[--brand-invert:1]'}
        style={{ ...style, objectFit: 'contain' } as BrandCSSProperties} />
);

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const OneSignalNodeComponent = (props: NodeProps) => (
    <AutomationNode {...props} Icon={OfficialBrandIcon} iconColor="text-red-500" />
);

export const OneSignalNode: NodeDefinition = {
    type: 'automation-onesignal',
    label: 'OneSignal',
    description: 'Send messages and manage audiences, templates, and journeys',
    Icon: OfficialBrandIcon,
    iconColor: 'text-red-500',
    dimensions: DIMENSIONS,
    component: memo(OneSignalNodeComponent),
};
