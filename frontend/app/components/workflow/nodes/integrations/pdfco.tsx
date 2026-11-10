import { memo, type CSSProperties } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition } from '~/components/workflow/nodes/types';

// Unmodified PDF.co brand artwork published at https://pdf.co/.
const PDFCoIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/pdfco-brand.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' }} />
);

export const PDFCoNode: NodeDefinition = {
    type: 'automation-pdfco',
    label: 'PDF.co',
    description: 'Extract invoice data, convert documents, generate and edit PDFs',
    category: 'documents',
    keywords: ['pdfco', 'invoice', 'OCR', 'spreadsheet', 'document parser'],
    Icon: PDFCoIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={PDFCoIcon} iconColor="" />),
};
