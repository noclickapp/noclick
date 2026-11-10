import { memo } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition } from '~/components/workflow/nodes/types';


import type { CSSProperties as BrandCSSProperties } from 'react';
import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
// Vector brand artwork from https://bizzabo.com
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <ThemedBrandImg light="/icons/bizzabo-brand-vector.svg" className={className} style={style} />
);

export const BizzaboNode: NodeDefinition = {
    type: 'automation-bizzabo',
    label: 'Bizzabo',
    description: 'Account events, sessions, speakers and scoped contact metadata',
    category: 'bookings',
    keywords: ['events', 'contacts', 'sessions', 'speakers', 'partners', 'registrations'],
    Icon: OfficialBrandIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 62 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={OfficialBrandIcon} iconColor="" />),
};
