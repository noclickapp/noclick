import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const PhoneHarnessIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/phone-harness.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const PhoneHarnessNode: NodeDefinition = {
    type: 'automation-phone-harness', category: 'developer-tools', label: 'Phone Harness',
    description: 'Manage phone sessions, ADB access, account keys and session history',
    keywords: ['Android', 'iPhone', 'emulator', 'mobile testing', 'ADB'],
    Icon: PhoneHarnessIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={PhoneHarnessIcon} iconColor="" />),
};
