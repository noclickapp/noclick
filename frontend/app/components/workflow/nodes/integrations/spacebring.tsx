// Native Spacebring customer network, resource and booking metadata workflows.
// Current credential forms, scoped pickers and Debug output share automation seams.
import { memo } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition } from '~/components/workflow/nodes/types';


import type { CSSProperties as BrandCSSProperties } from 'react';
// Vector brand artwork from https://www.spacebring.com/media-kit
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <>
        <img src="/icons/spacebring-brand-vector.svg" alt="" aria-hidden="true" className={`${className ?? ''} dark:hidden`}
            style={{ ...style, objectFit: 'contain' } as BrandCSSProperties} />
        <img src="/icons/spacebring-brand-vector-dark.svg" alt="" aria-hidden="true" className={`${className ?? ''} hidden dark:block`}
            style={{ ...style, objectFit: 'contain' } as BrandCSSProperties} />
    </>
);

export const SpacebringNode: NodeDefinition = {
    type: 'automation-spacebring',
    label: 'Spacebring',
    description: 'Read network, location, resource and membership metadata; update resource and booking descriptions',
    category: 'bookings',
    keywords: ['Spacebring', 'andcards', 'coworking', 'location', 'resource', 'membership', 'booking', 'availability'],
    Icon: OfficialBrandIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={OfficialBrandIcon} iconColor="" />),
};
