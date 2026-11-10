/** Registers Airflow's stable API node in the workflow and integration catalogs.
 * Supplies the provider label, category and official icon for its generated schema. */
import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const ApacheIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/apache.png" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
ApacheIcon.displayName = 'ApacheIcon';

export const ApacheNode: NodeDefinition = {
    type: 'automation-apache',
    label: 'Airflow API (Stable)',
    description: 'Manage Apache Airflow DAGs, runs, tasks, variables and pools; trigger workflows on new runs.',
    category: 'developer-tools',
    keywords: ['apache', 'airflow', 'DAG', 'orchestration', 'pipeline', 'ETL'],
    Icon: ApacheIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={ApacheIcon} iconColor="" />),
};
