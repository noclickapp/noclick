// Microsoft Word automation node definition.
// Provides comprehensive Word document operations via Microsoft Graph API.
// Supports document management, content operations, sharing, permissions, version control, and search.

import { memo, forwardRef, SVGProps, useId } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 60 };

// Official Microsoft Word 2025 logo from Wikipedia
const WordIcon: SvgIconComponent = forwardRef<SVGSVGElement, SVGProps<SVGSVGElement>>(
    ({ className, style, ...props }, ref) => {
        const grad1 = useId();
        const grad2 = useId();
        const grad3 = useId();
        const grad4 = useId();
        const grad5 = useId();
        const grad6 = useId();
        const grad7 = useId();
        const grad8 = useId();

        return (
            <svg
                ref={ref}
                xmlns="http://www.w3.org/2000/svg"
                viewBox="0 0 35 36"
                className={className}
                style={style}
                {...props}
            >
                <defs>
                    <radialGradient id={grad1} cx="-619.29" cy="488.84" fx="-619.29" fy="488.84" r="1" gradientTransform="translate(29495.74 9885.89) scale(47.57 -20.15)" gradientUnits="userSpaceOnUse">
                        <stop offset=".18" stopColor="#1657f4"/>
                        <stop offset=".57" stopColor="#0036c4"/>
                    </radialGradient>
                    <linearGradient id={grad2} x1="5" y1="97" x2="27.97" y2="97" gradientTransform="translate(0 116) scale(1 -1)" gradientUnits="userSpaceOnUse">
                        <stop offset="0" stopColor="#66c0ff"/>
                        <stop offset=".26" stopColor="#0094f0"/>
                    </linearGradient>
                    <radialGradient id={grad3} cx="-637.72" cy="517.98" fx="-637.72" fy="517.98" r="1" gradientTransform="translate(-40017.96 -12225.34) rotate(133.55) scale(29.36 -72.32)" gradientUnits="userSpaceOnUse">
                        <stop offset=".14" stopColor="#d471ff"/>
                        <stop offset=".83" stopColor="#509df5" stopOpacity="0"/>
                    </radialGradient>
                    <radialGradient id={grad4} cx="-611.76" cy="514.18" fx="-611.76" fy="514.18" r="1" gradientTransform="translate(-52234.57 11411.47) rotate(90) scale(18.62 -101.65)" gradientUnits="userSpaceOnUse">
                        <stop offset=".28" stopColor="#4f006f" stopOpacity="0"/>
                        <stop offset="1" stopColor="#4f006f"/>
                    </radialGradient>
                    <linearGradient id={grad5} x1="5" y1="107.22" x2="35" y2="106.72" gradientTransform="translate(0 116) scale(1 -1)" gradientUnits="userSpaceOnUse">
                        <stop offset="0" stopColor="#9deaff"/>
                        <stop offset=".2" stopColor="#3bd5ff"/>
                    </linearGradient>
                    <radialGradient id={grad6} cx="-650.27" cy="515.34" fx="-650.27" fy="515.34" r="1" gradientTransform="translate(-26921.47 -31089.42) rotate(166.85) scale(29.49 -70.64)" gradientUnits="userSpaceOnUse">
                        <stop offset=".06" stopColor="#e4a7fe"/>
                        <stop offset=".54" stopColor="#e4a7fe" stopOpacity="0"/>
                    </radialGradient>
                    <radialGradient id={grad7} cx="-600.8" cy="515.58" fx="-600.8" fy="515.58" r="1" gradientTransform="translate(1363.5 17878.99) rotate(45) scale(22.63 -22.63)" gradientUnits="userSpaceOnUse">
                        <stop offset=".08" stopColor="#367af2"/>
                        <stop offset=".87" stopColor="#001a8f"/>
                    </radialGradient>
                    <radialGradient id={grad8} cx="-598.04" cy="557.24" fx="-598.04" fy="557.24" r="1" gradientTransform="translate(-7105.12 6724.6) rotate(90) scale(11.2 -12.77)" gradientUnits="userSpaceOnUse">
                        <stop offset=".59" stopColor="#2763e5" stopOpacity="0"/>
                        <stop offset=".97" stopColor="#58aafe"/>
                    </radialGradient>
                </defs>
                <path d="M5,27.09l14-17.09,16,11.11v11.39c0,1.93-1.57,3.5-3.5,3.5H11c-3.31,0-6-2.69-6-6v-2.91Z" fill={`url(#${grad1})`}/>
                <path d="M5,15.04c0-2.49,2.01-4.5,4.5-4.5h20.39l5.11-2.54v12.5c0,1.93-1.57,3.5-3.5,3.5H11c-3.31,0-6,2.69-6,6v-14.96Z" fill={`url(#${grad2})`}/>
                <path d="M5,15.04c0-2.49,2.01-4.5,4.5-4.5h20.39l5.11-2.54v12.5c0,1.93-1.57,3.5-3.5,3.5H11c-3.31,0-6,2.69-6,6v-14.96Z" fill={`url(#${grad3})`} fillOpacity=".6"/>
                <path d="M5,15.04c0-2.49,2.01-4.5,4.5-4.5h20.39l5.11-2.54v12.5c0,1.93-1.57,3.5-3.5,3.5H11c-3.31,0-6,2.69-6,6v-14.96Z" fill={`url(#${grad4})`} fillOpacity=".1"/>
                <path d="M5,6C5,2.69,7.69,0,11,0h20.5c1.93,0,3.5,1.57,3.5,3.5v5c0,1.93-1.57,3.5-3.5,3.5H11c-3.31,0-6,2.69-6,6V6Z" fill={`url(#${grad5})`}/>
                <path d="M5,6C5,2.69,7.69,0,11,0h20.5c1.93,0,3.5,1.57,3.5,3.5v5c0,1.93-1.57,3.5-3.5,3.5H11c-3.31,0-6,2.69-6,6V6Z" fill={`url(#${grad6})`} fillOpacity=".8"/>
                <rect y="17" width="16" height="16" rx="3.25" ry="3.25" fill={`url(#${grad7})`}/>
                <rect y="17" width="16" height="16" rx="3.25" ry="3.25" fill={`url(#${grad8})`} fillOpacity=".65"/>
                <path d="M13.49,20.43l-1.97,9.14h-2.35s-1.16-5.48-1.16-5.48l-1.22,5.49h-2.38l-1.89-9.14h1.94l1.17,6.03,1.16-6.03h2.38l1.21,6.03,1.14-6.03h1.97Z" fill="#fff"/>
            </svg>
        );
    }
);
WordIcon.displayName = 'WordIcon';

const WordNodeComponent = (props: NodeProps) => {
    return (
        <AutomationNode
            {...props}
            Icon={WordIcon}
            iconColor=""
            width={DIMENSIONS.width}
            height={DIMENSIONS.height}
            iconSize={DIMENSIONS.iconSize}
        />
    );
};

export const WordNode: NodeDefinition = {
    type: 'automation-word',
    label: 'Word',
    description: 'Word automation',
    Icon: WordIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(WordNodeComponent),
};
