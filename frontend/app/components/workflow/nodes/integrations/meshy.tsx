// Meshy's task API creates 3D assets and tracks their asynchronous progress.
// This definition makes the self-registering integration discoverable in the canvas and catalog.
import { memo, forwardRef } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const MeshyIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/meshy.png" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
MeshyIcon.displayName = 'MeshyIcon';

export const MeshyNode: NodeDefinition = {
    type: 'automation-meshy',
    label: 'Meshy',
    category: 'ai',
    description: 'Generate, texture and remesh 3D models; track tasks and account credits',
    keywords: ['3d', 'models', 'textures', 'image to 3d', 'text to 3d'],
    Icon: MeshyIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={MeshyIcon} iconColor="" />),
};
