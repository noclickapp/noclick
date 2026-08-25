// ClickHouse Cloud management automation node definition.
// Provides workflow integration with the ClickHouse Cloud control-plane API
// (organizations, services, query endpoints, backups, ClickPipes, keys, members).

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const ClickHouseIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <img
        ref={ref}
        src="/icons/clickhouse.svg"
        alt=""
        // NOT brand-mono: clickhouse's mark is light YELLOW (#FCFF74), not white —
        // inverting flips it to blue. Keep its brand color.
        className={className || ''}
        style={style}
        {...props}
    />
));
ClickHouseIcon.displayName = 'ClickHouseIcon';

const ClickHouseNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={ClickHouseIcon} iconColor="" />;
};

export const ClickHouseNode: NodeDefinition = {
    type: 'automation-clickhouse',
    label: 'ClickHouse',
    description: 'ClickHouse Cloud management automation',
    Icon: ClickHouseIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(ClickHouseNodeComponent),
};
