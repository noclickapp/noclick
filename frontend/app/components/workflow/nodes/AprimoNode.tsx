import { forwardRef } from 'react';
import type { ImgHTMLAttributes } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import type { NodeDefinition, SvgIconComponent } from './types';

const AprimoIcon: SvgIconComponent = forwardRef<HTMLImageElement, ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/aprimo.svg" alt="" className={className} {...props}
            style={{ ...style, objectFit: 'contain' }} />
    )
);
AprimoIcon.displayName = 'AprimoIcon';

export const AprimoNode: NodeDefinition = {
    type: 'automation-aprimo', category: 'media', label: 'Aprimo DAM',
    description: 'Classification-bound digital asset and schema metadata reads',
    keywords: ['Aprimo', 'DAM', 'digital asset management', 'content metadata', 'classification'],
    Icon: AprimoIcon, iconColor: '', dimensions: { width: 90, height: 90, iconSize: 48 },
    component: (props: NodeProps) => <AutomationNode {...props} Icon={AprimoIcon} iconColor="" />,
};
