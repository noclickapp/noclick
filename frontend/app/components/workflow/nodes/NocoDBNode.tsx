// NocoDB automation node definition.
// Provides workflow integration with NocoDB for records and base metadata.

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';


// Unmodified compact brand asset from https://nocodb.com
import type { CSSProperties as BrandCSSProperties } from 'react';
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <img src="/icons/nocodb-brand.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as BrandCSSProperties} />
);

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const NocoDBIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img
            ref={ref}
            src="/icons/nocodb.svg"
            alt=""
            className={className}
            style={style}
            {...props}
        />
    )
);
NocoDBIcon.displayName = 'NocoDBIcon';

const NocoDBNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={OfficialBrandIcon} iconColor="" />;
};

export const NocoDBNode: NodeDefinition = {
    type: 'automation-nocodb',
    label: 'NocoDB',
    description: 'NocoDB database automation',
    Icon: OfficialBrandIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(NocoDBNodeComponent),
};
