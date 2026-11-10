import { memo } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition } from '~/components/workflow/nodes/types';


import type { CSSProperties as BrandCSSProperties } from 'react';
// Vector brand artwork from https://cdnlogo.com/logo/constant-contact_135071.html
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <img src="/icons/constant-contact-brand-vector.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as BrandCSSProperties} />
);

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

export const ConstantContactNode: NodeDefinition = {
    type: 'automation-constant-contact',
    label: 'Constant Contact',
    category: 'marketing',
    description: 'Manage contacts, lists, campaigns, and reports',
    Icon: OfficialBrandIcon,
    iconColor: 'text-blue-500',
    dimensions: DIMENSIONS,
    component: memo((props: NodeProps) => (
        <AutomationNode {...props} Icon={OfficialBrandIcon} iconColor="text-blue-500" />
    )),
};
