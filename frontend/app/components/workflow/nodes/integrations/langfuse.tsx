// Registers the Langfuse canvas node and its AI catalog category. The official icon identifies project API automations in the workflow editor.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const LangfuseIcon = ({
    className,
    style,
}: {
    className?: string;
    style?: CSSProperties;
}) => (
    <img
        src="/icons/langfuse.svg"
        alt=""
        aria-hidden="true"
        className={className}
        style={{ ...style, objectFit: 'contain' }}
    />
);

export const LangfuseNode: NodeDefinition = {
    type: 'automation-langfuse',
    category: 'ai',
    label: 'Langfuse',
    description:
        'Manage prompts, evaluation datasets, observations, scores and comments',
    Icon: LangfuseIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => (
        <AutomationNode {...props} Icon={LangfuseIcon} iconColor="" />
    )),
};
