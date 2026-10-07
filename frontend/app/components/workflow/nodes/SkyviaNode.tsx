// Native Skyvia workspace and management metadata node.
// Uses the current shared editor shell and exact official vendor SVG.
import { forwardRef, memo } from 'react';
import type { ImgHTMLAttributes } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import type { NodeDefinition, SvgIconComponent } from './types';

const SkyviaIcon: SvgIconComponent = forwardRef<HTMLImageElement, ImgHTMLAttributes<HTMLImageElement>>(
    (props, ref) => <img {...props} ref={ref} src="/icons/skyvia.svg" alt="" />
);
SkyviaIcon.displayName = 'SkyviaIcon';
export const SkyviaNode: NodeDefinition = {
    type: 'automation-skyvia', label: 'Skyvia',
    description: 'Read workspace, connection, integration, backup and automation metadata',
    Icon: SkyviaIcon, iconColor: '', dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={SkyviaIcon} iconColor="" />),
};
