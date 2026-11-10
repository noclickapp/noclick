import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const LambdaTestIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <>
        <img src="/icons/lambdatest.svg" alt="" aria-hidden="true"
            className={`${className ?? ''} dark:hidden`} style={style} />
        <img src="/icons/lambdatest-dark.svg" alt="" aria-hidden="true"
            className={`${className ?? ''} hidden dark:block`} style={style} />
    </>
);

export const LambdaTestNode: NodeDefinition = {
    type: 'automation-lambdatest',
    category: 'developer-tools',
    label: 'LambdaTest',
    description: 'Start and stop screenshot tests, retrieve images and ZIP URLs, and discover browser, device, profile and location options.',
    keywords: ['TestMu AI', 'screenshots', 'cross browser', 'visual testing'],
    Icon: LambdaTestIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 42 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={LambdaTestIcon} iconColor="" />),
};
