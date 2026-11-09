import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const InforUMobileIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/inforumobile.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const InforUMobileNode: NodeDefinition = {
    type: 'automation-inforumobile', category: 'communication', label: 'InforUMobile',
    description: 'Send SMS, WhatsApp and email; manage contacts and groups',
    Icon: InforUMobileIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={InforUMobileIcon} iconColor="" />),
};
