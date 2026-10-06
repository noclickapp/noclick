// Native Qonversion v4 metadata node for products, definitions, configuration status and opted-in users.
// Uses the exact official public PNG; credential and operation forms come from its generated native schema.
import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };
const QonversionIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => <img ref={ref} src="/icons/qonversion.png" alt="" className={className} style={style} {...props} />
);
QonversionIcon.displayName = 'QonversionIcon';
const QonversionNodeComponent = (props: NodeProps) => <AutomationNode {...props} Icon={QonversionIcon} iconColor="#19191b" />;
export const QonversionNode: NodeDefinition = {
    type: 'automation-qonversion', label: 'Qonversion',
    description: 'Read product, entitlement definition, configuration and safe user metadata',
    Icon: QonversionIcon, iconColor: '#19191b', dimensions: DIMENSIONS, component: memo(QonversionNodeComponent),
};
