// Grafana canvas and catalog definition, discovered by the integration loader.
// Keep provider presentation here so this integration needs no shared registry edits.
import { forwardRef, memo } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const GrafanaIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/grafana.svg" alt="" className={className} style={style} {...props} />
    )
);
GrafanaIcon.displayName = 'GrafanaIcon';

const GrafanaNodeComponent = (props: NodeProps) => (
    <AutomationNode {...props} Icon={GrafanaIcon} iconColor="" iconSize={56} />
);

export const GrafanaNode: NodeDefinition = {
    type: 'automation-grafana',
    label: 'Grafana',
    description: 'Dashboards and observability',
    category: 'monitoring',
    keywords: ['dashboard', 'observability', 'monitoring', 'alerting', 'data source', 'annotation', 'metrics'],
    Icon: GrafanaIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 42 },
    component: memo(GrafanaNodeComponent),
};
