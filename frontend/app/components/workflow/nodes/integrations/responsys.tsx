import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

// Unmodified Oracle wordmark: https://www.oracle.com/apac/news/resources/
const ResponsysIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/responsys.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);
const Component = (props: NodeProps) => <AutomationNode {...props} Icon={ResponsysIcon} iconColor="" />;
export const ResponsysNode: NodeDefinition = {
    type: 'automation-responsys', label: 'Oracle Responsys',
    description: 'Account, folder, list, table and campaign metadata',
    keywords: ['Oracle', 'Responsys', 'folder', 'profile list', 'supplemental table', 'campaign metadata', 'organization'],
    Icon: ResponsysIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 }, component: memo(Component),
};
