// Native Northflank project and workload metadata provider.
// Uses the existing automation renderer and supplied token credential UI.
import { memo } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';
// Exact official gradient mark used by the native picker and canvas.
// Preserve its colors and the canvas's supplied disabled filter.
import { forwardRef, type ImgHTMLAttributes } from 'react';

export const NorthflankIcon = forwardRef<HTMLImageElement, Pick<ImgHTMLAttributes<HTMLImageElement>, 'className' | 'style'>>(({ className, style }, ref) => (
    <img ref={ref} src="/icons/northflank.svg" alt="Northflank" className={className} style={{ ...style, objectFit: 'contain' }} />
));
NorthflankIcon.displayName = 'NorthflankIcon';


const Component = (props: NodeProps) => <AutomationNode {...props} Icon={NorthflankIcon} iconColor="" />;
export const NorthflankNode: NodeDefinition = {
    type: 'automation-northflank', category: 'cloud-hosting', label: 'Northflank',
    description: 'Project, service, deployment, job and addon metadata with empty-project management',
    Icon: NorthflankIcon, iconColor: '', dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo(Component),
};
