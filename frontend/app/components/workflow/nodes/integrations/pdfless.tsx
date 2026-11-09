import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const PdflessIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/pdfless.png" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' } as CSSProperties} />
);

export const PdflessNode: NodeDefinition = {
    type: 'automation-pdfless', category: 'documents', label: 'Pdfless',
    description: 'Generate PDFs from templates, list templates and read workspace quota',
    keywords: ['pdf', 'documents', 'templates', 'invoices'],
    Icon: PdflessIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={PdflessIcon} iconColor="" />),
};
