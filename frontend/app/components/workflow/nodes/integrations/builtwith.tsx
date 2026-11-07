// Native BuiltWith domain technology lookup in the workflow editor.
// Uses the original PR’s BuiltWith brand artwork.
// The operation runs only when explicitly executed; connecting a key makes no lookup.
import { memo } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';


import type { CSSProperties as BrandCSSProperties } from 'react';
// Vector brand artwork from https://logos-download.com/77095-builtwith-pty-ltd-logo-download.html
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <img src="/icons/builtwith-brand-vector.svg" alt="" aria-hidden="true" className={(className || '') + ' [--brand-invert:0] dark:[--brand-invert:1]'}
        style={{ ...style, filter: "brightness(0) invert(var(--brand-invert, 0))", objectFit: 'contain' } as BrandCSSProperties} />
);

export const BuiltWithNode: NodeDefinition = {
    type: 'automation-builtwith',
    label: 'BuiltWith',
    description: 'Look up technologies used by public root domains',
    keywords: ['website', 'technology', 'domain', 'stack', 'BuiltWith'],
    Icon: OfficialBrandIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={OfficialBrandIcon} iconColor="" />),
};
