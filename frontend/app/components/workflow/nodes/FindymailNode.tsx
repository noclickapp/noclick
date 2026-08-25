// Findymail B2B email/phone enrichment automation node definition.
// Provides workflow integration with the Findymail REST API (finder, verifier,
// intellimatch, signals, lists, credits) plus a webhook trigger for signal matches.

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const FindymailIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <img ref={ref} src="/icons/findymail.svg" alt="" className={className} style={style} {...props} />
));
FindymailIcon.displayName = 'FindymailIcon';

const FindymailNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={FindymailIcon} iconColor="" />;
};

export const FindymailNode: NodeDefinition = {
    type: 'automation-findymail',
    label: 'Findymail',
    description: 'Findymail B2B email & phone enrichment',
    Icon: FindymailIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(FindymailNodeComponent),
};
