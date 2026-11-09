import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const MEQRQRCodeIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/me-qr-qr-code.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const MEQRQRCodeNode: NodeDefinition = {
    type: 'automation-me-qr-qr-code', category: 'marketing', label: 'ME-QR QR Code',
    description: 'Create and update QR codes and short links, manage folders, and read scan analytics',
    Icon: MEQRQRCodeIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={MEQRQRCodeIcon} iconColor="" />),
};
