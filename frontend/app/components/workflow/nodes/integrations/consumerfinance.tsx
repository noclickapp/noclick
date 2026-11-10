// Makes CFPB complaint searches and polling discoverable in the workflow catalog.
// The definition uses the agency's official icon and needs no account connection.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const ConsumerfinanceIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/consumerfinance.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' } as CSSProperties} />
);

export const ConsumerfinanceNode: NodeDefinition = {
    type: 'automation-consumerfinance',
    label: 'The Consumer Financial Protection Bureau',
    category: 'finance-accounting',
    description: 'Search public consumer complaints, suggest companies and ZIP codes, and watch for new complaints',
    keywords: ['CFPB', 'consumerfinance', 'consumer complaints', 'financial protection'],
    Icon: ConsumerfinanceIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={ConsumerfinanceIcon} iconColor="" />),
};
