// Formstack's catalog and canvas definition is discovered by the integration loader.
// Its generated schema supplies the operation and credential forms.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const FormstackIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/formstack.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const FormstackNode: NodeDefinition = {
    type: 'automation-formstack', category: 'forms', label: 'Formstack',
    description: 'Manage forms, submissions, fields, folders and webhooks with Formstack Forms',
    keywords: ['survey', 'form builder', 'submission', 'data collection'],
    Icon: FormstackIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={FormstackIcon} iconColor="" />),
};
