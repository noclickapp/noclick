// PowerPoint's definition makes its Graph file actions discoverable in the catalog.
// The publisher icon is recorded with a separate provenance sidecar.
import { memo, forwardRef } from 'react';
import type { ImgHTMLAttributes } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const PowerPointIcon: SvgIconComponent = forwardRef<HTMLImageElement, ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/microsoft-powerpoint.svg" alt="" className={className} style={style} {...props} />
    ),
);
PowerPointIcon.displayName = 'PowerPointIcon';

export const MicrosoftPowerPointNode: NodeDefinition = {
    type: 'automation-microsoft-powerpoint',
    label: 'Microsoft PowerPoint',
    description: 'Manage, copy, share and version PowerPoint files in OneDrive and SharePoint',
    category: 'microsoft',
    keywords: ['ppt', 'pptx', 'slide deck', 'presentation', 'template'],
    Icon: PowerPointIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={PowerPointIcon} iconColor="" />),
};
