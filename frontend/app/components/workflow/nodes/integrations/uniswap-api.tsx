import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const UniswapAPIIcon = ({
    className,
    style,
}: {
    className?: string;
    style?: CSSProperties;
}) => (
    <img
        src="/icons/uniswap-api.svg"
        alt=""
        aria-hidden="true"
        className={className}
        style={{ ...style, objectFit: 'contain' }}
    />
);

export const UniswapAPINode: NodeDefinition = {
    type: 'automation-uniswap-api',
    category: 'finance-accounting',
    label: 'Uniswap API',
    description:
        'Get quotes, approvals, swap calldata and status, and submit signed gasless orders',
    Icon: UniswapAPIIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => (
        <AutomationNode {...props} Icon={UniswapAPIIcon} iconColor="" />
    )),
};
