// Bandsintown's self-registering canvas and integration catalog definition.
// The icon is the provider's published asset, with provenance recorded beside it.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const BandsintownIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/bandsintown.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const BandsintownNode: NodeDefinition = {
    type: 'automation-bandsintown', category: 'bookings', label: 'Bandsintown',
    description: 'Look up artist profiles and read tour dates, venues, lineups and ticket offers',
    keywords: ['music', 'concerts', 'tour dates', 'artist', 'tickets'],
    Icon: BandsintownIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={BandsintownIcon} iconColor="" />),
};
