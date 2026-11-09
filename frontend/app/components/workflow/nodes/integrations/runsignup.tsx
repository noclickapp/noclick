import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const RunSignupIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/runsignup.svg" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
RunSignupIcon.displayName = 'RunSignupIcon';

// Exact publisher asset; provenance is recorded beside the SVG.
export const RunSignupNode: NodeDefinition = {
    type: 'automation-runsignup',
    label: 'RunSignup',
    description: 'Automate races, participants, donations, teams, coupons and results',
    category: 'industry',
    keywords: ['race registration', 'fundraising', 'running', 'RunSignUp'],
    Icon: RunSignupIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={RunSignupIcon} iconColor="" />),
};
