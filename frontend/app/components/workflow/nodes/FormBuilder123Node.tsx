import type { SVGProps } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import type { NodeDefinition } from './types';

export const FormBuilder123Icon = ({ className, style }: SVGProps<SVGSVGElement>) => (
    <img src="/icons/123formbuilder.svg" alt="123FormBuilder" className={className} style={style} />
);

export const FormBuilder123Node: NodeDefinition = {
    type: 'automation-123formbuilder',
    label: '123FormBuilder',
    description: 'Read form, field and submission metadata; organize forms and folders',
    keywords: ['123', 'forms', 'surveys', 'submissions', 'folders'],
    Icon: FormBuilder123Icon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: (props: NodeProps) => <AutomationNode {...props} Icon={FormBuilder123Icon} iconColor="" />,
};
