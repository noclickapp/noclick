import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const MercuryIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <>
            <img ref={ref} src="/icons/mercury.svg" alt="" className={`${className ?? ''} dark:hidden`} style={{ ...style, objectFit: 'contain' }} {...props} />
            <img src="/icons/mercury-dark.svg" alt="" className={`${className ?? ''} hidden dark:block`} style={{ ...style, objectFit: 'contain' }} {...props} />
        </>
    ),
);
MercuryIcon.displayName = 'MercuryIcon';

// Exact publisher asset; provenance is recorded beside the SVG.
export const MercuryNode: NodeDefinition = {
    type: 'automation-mercury',
    label: 'Mercury',
    description: 'Accounts, transactions, payments, recipients, customers and invoices',
    category: 'finance-accounting',
    keywords: ['bank', 'banking', 'payments', 'transfers', 'invoices'],
    Icon: MercuryIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={MercuryIcon} iconColor="" />),
};
