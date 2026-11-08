// Defines Coda in the integration catalog and workflow canvas.
// Discovery loads this provider definition without a shared registry entry.
import { forwardRef } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';
const CodaIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => <img ref={ref} src="/icons/coda-preferred-brand.svg" alt="" className={className} style={style} {...props} />,
);
CodaIcon.displayName = 'CodaIcon';
const Component = (props: NodeProps) => <AutomationNode {...props} Icon={CodaIcon} iconColor="" />;
export const CodaNode: NodeDefinition = {
    type: 'automation-coda', category: 'productivity', label: 'Coda', description: 'Manage Coda docs, pages, tables, rows, formulas, controls, folders and sharing.',
    Icon: CodaIcon, iconColor: '', dimensions: { width: 110, height: 90, iconSize: 48 }, component: Component,
};
