// Zuora's self-registering canvas and catalog definition.
// The node uses the provider brand mark to identify its tenant metadata operations.
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';
const ZuoraIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/zuora.svg" alt="" aria-hidden="true" className={className} style={{ ...style, objectFit: 'contain' }} />
);
const ZuoraComponent = (props: NodeProps) => <AutomationNode {...props} Icon={ZuoraIcon} iconColor="" />;
export const ZuoraNode: NodeDefinition = {
    type: 'automation-zuora', category: 'finance-accounting', label: 'Zuora', description: 'Read tenant metadata and update account, contact, product and subscription metadata',
    Icon: ZuoraIcon, iconColor: '', dimensions: { width: 90, height: 90, iconSize: 48 }, component: ZuoraComponent,
};
