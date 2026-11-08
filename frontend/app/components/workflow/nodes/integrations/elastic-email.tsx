// Elastic Email's native node uses the shared automation renderer.
// The official Email API mark keeps this integration recognizable in both palettes.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const ElasticEmailIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/elastic-email.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const ElasticEmailNode: NodeDefinition = {
    type: 'automation-elastic-email',
    label: 'Elastic Email',
    category: 'marketing',
    description: 'Manage contacts, lists and templates, send transactional email and check delivery status',
    keywords: ['elasticemail', 'email marketing', 'transactional email', 'mailing lists'],
    Icon: ElasticEmailIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={ElasticEmailIcon} iconColor="" />),
};
