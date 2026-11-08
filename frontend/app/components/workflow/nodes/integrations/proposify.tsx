import { memo, forwardRef } from 'react';
import type { HTMLAttributes } from 'react';
import type { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';


import type { CSSProperties as BrandCSSProperties } from 'react';
// Vector brand artwork from https://proposify.com
const OfficialBrandIcon = ({ className, style }: { className?: string; style?: BrandCSSProperties }) => (
    <img src="/icons/proposify-brand-vector.svg" alt="" aria-hidden="true" className={className}
        style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as BrandCSSProperties} />
);

const Component = (props: NodeProps) => <AutomationNode {...props} Icon={OfficialBrandIcon} iconColor="" />;
export const ProposifyNode: NodeDefinition = {
    type: 'automation-proposify', category: 'documents', label: 'Proposify',
    description: 'Proposify Connect metadata and V3 draft-document workflows with issued OAuth',
    Icon: OfficialBrandIcon, iconColor: '', dimensions: { width: 90, height: 90, iconSize: 48 },
    component: memo(Component),
};

// Exact official light/dark Proposify SVGs; preserve colors and the real canvas filter.

export const ProposifyIcon = forwardRef<HTMLSpanElement, Pick<HTMLAttributes<HTMLSpanElement>, 'className' | 'style'>>(
    ({ className, style, ...props }, ref) => (
        <span {...props} ref={ref} className={className} style={{ ...style, display: 'inline-flex' }}>
            <img src="/icons/proposify.svg" alt="" className="block dark:hidden" style={{ width: '100%', height: '100%', objectFit: 'contain' }} />
            <img src="/icons/proposify-dark.svg" alt="" className="hidden dark:block" style={{ width: '100%', height: '100%', objectFit: 'contain' }} />
        </span>
    ),
);
ProposifyIcon.displayName = 'ProposifyIcon';
