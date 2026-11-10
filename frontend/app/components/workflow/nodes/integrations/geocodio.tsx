import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const GeocodioIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/geocodio.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const GeocodioNode: NodeDefinition = {
    type: 'automation-geocodio', category: 'developer-tools', label: 'Geocodio',
    description: 'Geocode addresses, calculate distances and process spreadsheets',
    Icon: GeocodioIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={GeocodioIcon} iconColor="" />),
};
