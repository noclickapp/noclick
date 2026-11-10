// ClickSend catalog and canvas definition discovered by the integration loader.
// Keeping it here avoids shared registry entries.
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';
import type { CSSProperties } from 'react';
const Icon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
  <img src="/icons/clicksend-preferred-brand.svg" alt="" aria-hidden="true" className={className}
    style={{ ...style, objectFit: 'contain' }} />
);
const Component = (props: NodeProps) => <AutomationNode {...props} Icon={Icon} iconColor="" />;
export const ClickSendNode: NodeDefinition = {
  type: 'automation-clicksend', category: 'communication', label: 'ClickSend',
  description: 'SMS, MMS, email, contacts, campaigns, and messaging reports',
  Icon, iconColor: '', dimensions: { width: 90, height: 90, iconSize: 48 }, component: Component,
};
