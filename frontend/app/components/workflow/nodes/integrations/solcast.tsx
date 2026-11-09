// Solcast workflow definition discovered by the integration catalog.
// Connects the generated schema to its official service icon.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const SolcastIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/solcast.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const SolcastNode: NodeDefinition = {
    type: 'automation-solcast', category: 'industry', label: 'Solcast',
    description: 'Automate solar forecasts, weather data, sites, measurements and schedules',
    Icon: SolcastIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={SolcastIcon} iconColor="" />),
};
