// Registers Shlink's four protected metadata reads on the workflow canvas.
// The generated native schema supplies operation forms and scoped credentials.
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';
// Displays the unchanged official Shlink favicon SVG in its original blue.
// Contain preserves its geometry while the canvas supplies theme and disabled filters.
import { forwardRef, type ImgHTMLAttributes } from 'react';
const ShlinkIcon = forwardRef<HTMLImageElement, ImgHTMLAttributes<HTMLImageElement>>(
    ({ style, ...props }, ref) => <img {...props} ref={ref} src="/icons/shlink.svg" alt="" aria-hidden="true" style={{ ...style, objectFit: 'contain' }} />,
);
ShlinkIcon.displayName = 'ShlinkIcon';
export { ShlinkIcon };

const ShlinkNodeComponent = (props: NodeProps) => <AutomationNode {...props} Icon={ShlinkIcon as any} iconColor="" />;
export const ShlinkNode: NodeDefinition = {
    type: 'automation-shlink', label: 'Shlink',
    description: 'Current domain, tag and short URL metadata without redirect targets or tracking',
    keywords: ['Shlink', 'short URL metadata', 'domain', 'tag', 'validity', 'aggregate visits'],
    Icon: ShlinkIcon as any, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: ShlinkNodeComponent,
};
