import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const SelectPdfIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <>
        <img src="/icons/selectpdf.svg" alt="" aria-hidden="true" className={`${className ?? ''} dark:hidden`} style={style} />
        <img src="/icons/selectpdf-dark.svg" alt="" aria-hidden="true" className={`${className ?? ''} hidden dark:block`} style={style} />
    </>
);

export const SelectPdfNode: NodeDefinition = {
    type: 'automation-selectpdf', category: 'documents', label: 'SelectPdf',
    description: 'Convert HTML and URLs to PDF, merge PDFs, extract and search text, and read conversion usage',
    keywords: ['pdf', 'html', 'documents', 'conversion', 'merge', 'text extraction'],
    Icon: SelectPdfIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={SelectPdfIcon} iconColor="" />),
};
