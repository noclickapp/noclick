// Native Qonversion v4 metadata node for products, definitions, configuration status and opted-in users.
// Uses the exact official public PNG; credential and operation forms come from its generated native schema.
import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';


import type { CSSProperties as BrandCSSProperties } from 'react';
// Vector brand artwork from https://raw.githubusercontent.com/qonversion/android-sdk/adeeeae489191328b1c75190d96c2930f5101737/sample/src/main/res/drawable/ic_qonversion.xml
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <img src="/icons/qonversion-brand-vector.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as BrandCSSProperties} />
);

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };
const QonversionIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => <img ref={ref} src="/icons/qonversion.png" alt="" className={className} style={style} {...props} />
);
QonversionIcon.displayName = 'QonversionIcon';
const QonversionNodeComponent = (props: NodeProps) => <AutomationNode {...props} Icon={OfficialBrandIcon} iconColor="#19191b" />;
export const QonversionNode: NodeDefinition = {
    type: 'automation-qonversion', label: 'Qonversion',
    description: 'Read product, entitlement definition, configuration and safe user metadata',
    Icon: OfficialBrandIcon, iconColor: '#19191b', dimensions: DIMENSIONS, component: memo(QonversionNodeComponent),
};
