// Gusto payroll and HR workflow integration. Uses the provider's unmodified
// wordmark from its official logo pack to identify the connected service.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const GustoIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/gusto.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const GustoNode: NodeDefinition = {
    type: 'automation-gusto',
    label: 'Gusto',
    description: 'Manage Gusto companies, employees, payrolls and time off',
    category: 'hr-recruiting',
    keywords: ['payroll', 'employees', 'HR', 'PTO', 'time off'],
    Icon: GustoIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={GustoIcon} iconColor="" />),
};
