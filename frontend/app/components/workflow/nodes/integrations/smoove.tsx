/** Smoove's catalog and canvas definition uses the official API explorer mark.
 * The backend generates its operation schema and credential metadata independently.
 */
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const SmooveIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/smoove.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const SmooveNode: NodeDefinition = {
    type: 'automation-smoove', category: 'marketing', label: 'Smoove',
    description: 'Manage contacts, subscriptions and lists; read leads and campaign reports; log CRM notes',
    keywords: ['email marketing', 'mailing lists', 'leads', 'newsletter', 'CRM'],
    Icon: SmooveIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={SmooveIcon} iconColor="" />),
};
