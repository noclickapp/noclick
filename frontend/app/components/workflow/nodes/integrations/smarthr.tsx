// SmartHR's definition places its employee and organization actions in the catalog.
// Schemas and credential metadata are generated from the backend node.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const SmartHRIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/smarthr.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const SmartHRNode: NodeDefinition = {
    type: 'automation-smarthr', category: 'hr-recruiting', label: 'SmartHR',
    description: 'Start workflows from employee and dependent events; manage employees, departments, employment types and job titles',
    keywords: ['smarthr', 'human resources', 'employees', 'onboarding'],
    Icon: SmartHRIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={SmartHRIcon} iconColor="" />),
};
