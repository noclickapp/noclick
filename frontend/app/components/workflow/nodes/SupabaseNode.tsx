// Supabase REST API automation node definition.
// Provides workflow integration with Supabase PostgREST API for database operations.

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

// Create icon component from SVG file
const SupabaseIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img
            ref={ref}
            src="/icons/supabase.svg"
            alt=""
            className={className}
            style={style}
            {...props}
        />
    )
);
SupabaseIcon.displayName = 'SupabaseIcon';

const SupabaseNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={SupabaseIcon} iconColor="" />;
};

export const SupabaseNode: NodeDefinition = {
    type: 'automation-supabase',
    label: 'Supabase',
    description: 'Supabase automation',
    Icon: SupabaseIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(SupabaseNodeComponent),
};
