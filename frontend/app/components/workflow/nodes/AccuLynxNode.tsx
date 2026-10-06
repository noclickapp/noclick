// AccuLynx's native node exposes location-bound CRM metadata and ordinary management.
// The shared form renders the issued key and typed operation fields; the official
// wordmark keeps its source proportions in the canvas slot.
import { forwardRef } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import type { NodeDefinition, SvgIconComponent } from './types';

const AccuLynxIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => <img ref={ref} src="/icons/acculynx.svg" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />,
);
AccuLynxIcon.displayName = 'AccuLynxIcon';

export const AccuLynxNode: NodeDefinition = {
    type: 'automation-acculynx',
    label: 'AccuLynx',
    description: 'AccuLynx contacts, leads, jobs and company CRM metadata',
    Icon: AccuLynxIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: (props: NodeProps) => <AutomationNode {...props} Icon={AccuLynxIcon} iconColor="" />,
};
