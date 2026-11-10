import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const ImageChartsIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/image-charts.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const ImageChartsNode: NodeDefinition = {
    type: 'automation-image-charts', category: 'analytics-bi', label: 'Image-Charts',
    description: 'Render charts and QR codes as images with signed Enterprise requests',
    Icon: ImageChartsIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={ImageChartsIcon} iconColor="" />),
};
