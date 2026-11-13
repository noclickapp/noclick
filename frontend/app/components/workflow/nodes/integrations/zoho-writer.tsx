import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';
import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';

const ZohoWriterIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <ThemedBrandImg light="/icons/zoho-writer.svg" className={className} style={style} />
);

export const ZohoWriterNode: NodeDefinition = {
    type: 'automation-zoho-writer', category: 'documents', label: 'Zoho Writer',
    description: 'Create, find, update and publish documents and templates; watch document changes',
    Icon: ZohoWriterIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={ZohoWriterIcon} iconColor="" />),
};
