// ChurchTools native people, groups, calendars and wiki metadata node.
// Uses the sourced ChurchTools brand vector; credentials remain in the
// existing protected native credential form rather than node display data.
import { memo } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';
import type { CSSProperties as BrandCSSProperties } from 'react';
// Vector brand artwork from https://church.tools/en/press-center/
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <img src="/icons/churchtools-brand-vector.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as BrandCSSProperties} />
);

export const ChurchToolsNode: NodeDefinition = {
    type: 'automation-churchtools', label: 'ChurchTools',
    description: 'ChurchTools people, group, calendar and wiki metadata',
    Icon: OfficialBrandIcon, iconColor: '', dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={OfficialBrandIcon} iconColor="" />),
};
