// Microsoft To Do automation node definition.
// Provides task and task list management via Microsoft Graph API.
// Supports creating, updating, listing, and deleting tasks and task lists.

import { memo, forwardRef, SVGProps, useId } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 60 };

// Official Microsoft To Do icon SVG
const MicrosoftTodoIcon: SvgIconComponent = forwardRef<SVGSVGElement, SVGProps<SVGSVGElement>>(
    ({ className, style, ...props }, ref) => {
        const id = useId();
        // Generate unique IDs for gradients and masks to avoid conflicts
        const ids = {
            a: `${id}-a`,
            b: `${id}-b`,
            c: `${id}-c`,
            d: `${id}-d`,
            e: `${id}-e`,
            f: `${id}-f`,
            g: `${id}-g`,
            h: `${id}-h`,
            i: `${id}-i`,
        };

        return (
            <svg
                ref={ref}
                xmlns="http://www.w3.org/2000/svg"
                viewBox="0 0 1007.922 821.827"
                className={className}
                style={style}
                {...props}
            >
                <defs>
                    <style>{`.a{fill:#fff;}.b{fill:url(#${ids.a});}.c{mask:url(#${ids.b});}.d{fill:url(#${ids.c});}.e{mask:url(#${ids.d});}.f{fill:url(#${ids.e});}.g{fill:url(#${ids.f});}.h{mask:url(#${ids.g});}.i{fill:url(#${ids.h});}.j{fill:#195abd;}.k{fill:url(#${ids.i});}`}</style>
                    <linearGradient id={ids.a} x1="700.766" y1="597.024" x2="749.765" y2="597.024" gradientTransform="translate(86.603 -142.296) scale(0.867 1.307)" gradientUnits="userSpaceOnUse">
                        <stop offset="0" stopOpacity="0.13"/>
                        <stop offset="0.994" stopOpacity="0"/>
                    </linearGradient>
                    <mask id={ids.b} x="317.137" y="651.827" width="170" height="205.208" maskUnits="userSpaceOnUse">
                        <g transform="translate(-8.064 -116.521)">
                            <rect className="a" x="367.701" y="870.953" width="85" height="85" transform="translate(766.054 -22.512) rotate(45)"/>
                        </g>
                    </mask>
                    <radialGradient id={ids.c} cx="410.201" cy="853.349" r="85" gradientTransform="translate(715.49 -156.637) rotate(45)" gradientUnits="userSpaceOnUse">
                        <stop offset="0.5" stopOpacity="0.13"/>
                        <stop offset="0.994" stopOpacity="0"/>
                    </radialGradient>
                    <mask id={ids.d} x="837.922" y="95.835" width="205.208" height="205.208" maskUnits="userSpaceOnUse">
                        <g transform="translate(-8.064 -116.521)">
                            <rect className="a" x="876.038" y="260.012" width="170" height="85" transform="translate(1426.685 1195.977) rotate(-135)"/>
                        </g>
                    </mask>
                    <radialGradient id={ids.e} cx="1051.126" cy="1265.852" r="85" gradientTransform="translate(771.087 1854.394) rotate(-135)" xlinkHref={`#${ids.c}`}/>
                    <linearGradient id={ids.f} x1="1880.8" y1="34.286" x2="1929.799" y2="34.286" gradientTransform="matrix(0.867, 0, 0, -0.796, -1446.031, 767.147)" xlinkHref={`#${ids.a}`}/>
                    <mask id={ids.g} x="-35.208" y="299.482" width="205.208" height="205.208" maskUnits="userSpaceOnUse">
                        <g transform="translate(-8.064 -116.521)">
                            <rect className="a" x="-21.988" y="463.659" width="170" height="85" transform="translate(-339.453 192.807) rotate(-45)"/>
                        </g>
                    </mask>
                    <radialGradient id={ids.h} cx="27.608" cy="2001.37" r="85" gradientTransform="matrix(0.707, -0.707, -0.707, -0.707, 1480.66, 1854.394)" xlinkHref={`#${ids.c}`}/>
                    <linearGradient id={ids.i} x1="308.378" y1="811.629" x2="919.318" y2="200.689" gradientTransform="translate(-178.117 582.307) rotate(-45)" gradientUnits="userSpaceOnUse">
                        <stop offset="0" stopColor="#2987e6"/>
                        <stop offset="0.994" stopColor="#58c1f5"/>
                    </linearGradient>
                </defs>
                <rect className="b" x="694.422" y="269.785" width="42.5" height="736.5" transform="translate(652.71 -435.701) rotate(45)"/>
                <g className="c">
                    <circle className="d" cx="402.137" cy="736.827" r="85"/>
                </g>
                <g className="e">
                    <circle className="f" cx="922.922" cy="216.043" r="85"/>
                </g>
                <rect className="g" x="185.305" y="515.608" width="42.5" height="448.5" transform="translate(867.705 1000.439) rotate(135)"/>
                <g className="h">
                    <circle className="i" cx="85" cy="419.69" r="85"/>
                </g>
                <rect className="j" x="164.378" y="319.982" width="288" height="576" rx="42.5" transform="translate(-347.651 279.609) rotate(-45)"/>
                <rect className="k" x="469.848" y="74.159" width="288" height="864" rx="42.5" transform="translate(529.636 -402.327) rotate(45)"/>
            </svg>
        );
    }
);
MicrosoftTodoIcon.displayName = 'MicrosoftTodoIcon';

const MicrosoftTodoNodeComponent = (props: NodeProps) => {
    return (
        <AutomationNode
            {...props}
            Icon={MicrosoftTodoIcon}
            iconColor=""
            width={DIMENSIONS.width}
            height={DIMENSIONS.height}
            iconSize={DIMENSIONS.iconSize}
        />
    );
};

export const MicrosoftTodoNode: NodeDefinition = {
    type: 'automation-microsoft-todo',
    label: 'To Do',
    description: 'To Do automation',
    Icon: MicrosoftTodoIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(MicrosoftTodoNodeComponent),
};
