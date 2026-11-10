// Native BuiltWith domain technology lookup in the workflow editor.
// Uses the original PR’s BuiltWith brand artwork.
// The operation runs only when explicitly executed; connecting a key makes no lookup.
import { memo } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';


import type { CSSProperties as BrandCSSProperties } from 'react';
import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
// Vector brand artwork from https://logos-download.com/77095-builtwith-pty-ltd-logo-download.html
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <ThemedBrandImg light="/icons/builtwith-brand-vector.svg" dark="/icons/builtwith-brand-vector-dark.svg" className={className} style={style} />
);

export const BuiltWithNode: NodeDefinition = {
    type: 'automation-builtwith',
    label: 'BuiltWith',
    description: 'Look up technologies used by public root domains',
    category: 'content-research',
    keywords: ['website', 'technology', 'domain', 'stack', 'BuiltWith'],
    Icon: OfficialBrandIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={OfficialBrandIcon} iconColor="" />),
};
