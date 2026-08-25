// Extend (extend.ai) document AI automation node definition.
// Provides workflow integration with the Extend REST API (files, parse, extract,
// extractors, classify, split, edit, workflow runs) plus a webhook trigger for
// run-completed events.

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const ExtendIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <img
        ref={ref}
        src="/icons/extend.svg"
        alt=""
        className={`brand-mono ${className || ''}`}
        style={style}
        {...props}
    />
));
ExtendIcon.displayName = 'ExtendIcon';

const ExtendNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={ExtendIcon} iconColor="" />;
};

export const ExtendNode: NodeDefinition = {
    type: 'automation-extend',
    label: 'Extend',
    description: 'Extend document AI automation',
    Icon: ExtendIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(ExtendNodeComponent),
};
