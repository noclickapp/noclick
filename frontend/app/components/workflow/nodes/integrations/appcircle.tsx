// Appcircle's definition makes the native build and distribution actions discoverable.
// Generated backend schemas supply the credential and operation forms.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const AppcircleIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/appcircle.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const AppcircleNode: NodeDefinition = {
    type: 'automation-appcircle', category: 'developer-tools', label: 'Appcircle',
    description: 'Run mobile builds, manage testing groups and track build and task status.',
    keywords: ['mobile', 'ci', 'cd', 'ios', 'android', 'distribution'],
    Icon: AppcircleIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={AppcircleIcon} iconColor="" />),
};
