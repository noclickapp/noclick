// Native Oracle Fusion Cloud HCM metadata and location workflow definition.
// The schema supplies tenant-bound credentials and excludes payroll and employment writes.
import { forwardRef, memo } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


import type { CSSProperties as BrandCSSProperties } from 'react';
// Vector brand artwork from https://www.oracle.com/human-capital-management/
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <img src="/icons/oracle-hcm-brand-vector.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as BrandCSSProperties} />
);

const OracleHCMIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => <img ref={ref} src="/icons/oracle-hcm.svg" alt="" className={className} style={style} {...props} />,
);
OracleHCMIcon.displayName = 'OracleHCMIcon';

export const OracleHCMNode: NodeDefinition = {
    type: 'automation-oracle-hcm',
    label: 'Oracle Fusion Cloud HCM',
    description: 'HCM jobs, departments, locations and worker directory identifiers',
    category: 'hr-recruiting',
    Icon: OfficialBrandIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={OfficialBrandIcon} iconColor="" />),
};
