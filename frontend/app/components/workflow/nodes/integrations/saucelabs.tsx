import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const SauceLabsIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/saucelabs.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const SauceLabsNode: NodeDefinition = {
    type: 'automation-saucelabs', category: 'developer-tools', label: 'Sauce Labs',
    description: 'Manage real devices, sessions, apps, screenshots and hosted Appium',
    Icon: SauceLabsIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={SauceLabsIcon} iconColor="" />),
};
