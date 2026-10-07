// Linkwarden exposes closed collection/tag metadata reads in the native editor.
// The unchanged official PNG wordmark is separate from generated operation forms.
import { memo, forwardRef } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import type { NodeDefinition, SvgIconComponent } from './types';

const LinkwardenIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/linkwarden.png" alt="" className={className} style={{ ...style, objectFit: "contain" }} {...props} />
    ),
);
LinkwardenIcon.displayName = 'LinkwardenIcon';

export const LinkwardenNode: NodeDefinition = {
    type: 'automation-linkwarden',
    label: 'Linkwarden',
    description: 'Read scoped collection and tag metadata',
    Icon: LinkwardenIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => (
        <AutomationNode {...props} Icon={LinkwardenIcon} iconColor="" />
    )),
};
