import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const EzeepPrintingIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/ezeep-printing.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
);

export const EzeepPrintingNode: NodeDefinition = {
    type: 'automation-ezeep-printing', category: 'documents', label: 'ezeep Printing',
    description: 'Manage printers, print jobs, connectors, groups and printer profiles, and react to completed print jobs.',
    keywords: ['ezeep', 'printing', 'printers', 'print jobs'],
    Icon: EzeepPrintingIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={EzeepPrintingIcon} iconColor="" />),
};
