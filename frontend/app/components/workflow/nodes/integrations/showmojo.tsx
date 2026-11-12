// ShowMojo's catalog and canvas definition uses the official service mark.
// Its generated schema supplies the account token and operation forms.
import { memo } from 'react';
import type { CSSProperties } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';

const ShowMojoIcon = ({ className, style }: { className?: string; style?: CSSProperties }) => (
    <img src="/icons/showmojo.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, objectFit: 'contain' } as CSSProperties} />
);

export const ShowMojoNode: NodeDefinition = {
    type: 'automation-showmojo', category: 'industry', label: 'ShowMojo',
    description: 'Sync rental listings, export reports and schedule property tours',
    keywords: ['property management', 'real estate', 'showings', 'rental'],
    Icon: ShowMojoIcon, iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={ShowMojoIcon} iconColor="" />),
};
