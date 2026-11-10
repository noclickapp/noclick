import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const RemoveBgIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/remove-bg.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const RemoveBgNode: NodeDefinition = {
    type: 'automation-remove-bg', label: 'Remove Bg',
    category: 'media',
    description: 'Remove image backgrounds, replace backgrounds, crop subjects and check credits',
    Icon: RemoveBgIcon, iconColor: '', keywords: ['remove.bg', 'background removal', 'cutout', 'alpha mask'],
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={RemoveBgIcon} iconColor="" />),
};
