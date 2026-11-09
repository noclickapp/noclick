import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const QuickChartIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/quickchart.svg" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
QuickChartIcon.displayName = 'QuickChartIcon';

export const QuickChartNode: NodeDefinition = {
    type: 'automation-quickchart',
    label: 'QuickChart',
    description: 'Generate charts, QR codes, barcodes, tables, word clouds, and diagrams',
    category: 'media',
    keywords: ['chart.js', 'graphviz', 'qr', 'barcode', 'word cloud'],
    Icon: QuickChartIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={QuickChartIcon} iconColor="" />),
};
