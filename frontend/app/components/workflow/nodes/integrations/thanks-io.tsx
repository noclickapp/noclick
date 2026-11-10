import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const ThanksIoIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/thanks-io.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const ThanksIoNode: NodeDefinition = {
    type: 'automation-thanks-io', category: 'marketing', label: 'Thanks Io',
    description: 'Manage mailing lists, recipients, templates and postcard orders',
    Icon: ThanksIoIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={ThanksIoIcon} iconColor="" />),
};
