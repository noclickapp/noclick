import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const LapostaIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/laposta.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const LapostaNode: NodeDefinition = {
    type: 'automation-laposta', category: 'marketing', label: 'Laposta',
    description: 'Manage mailing lists, subscribers, custom fields, campaign content and reports',
    keywords: ['email marketing', 'newsletter', 'subscribers'],
    Icon: LapostaIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={LapostaIcon} iconColor="" />),
};
