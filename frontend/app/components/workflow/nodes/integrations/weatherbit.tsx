import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const WeatherbitIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <>
        <img src="/icons/weatherbit.svg" alt="" aria-hidden="true" className={`${className ?? ''} dark:hidden`} style={style} />
        <img src="/icons/weatherbit-dark.svg" alt="" aria-hidden="true" className={`${className ?? ''} hidden dark:block`} style={style} />
    </>
);

export const WeatherbitNode: NodeDefinition = {
    type: 'automation-weatherbit', category: 'content-research', label: 'Weatherbit',
    description: 'Get weather, forecasts, air quality and historical data, and watch for new lightning',
    Icon: WeatherbitIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={WeatherbitIcon} iconColor="" />),
};
