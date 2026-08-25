// Animated donut chart for the usage dashboard's by-type / by-model breakdown,
// with center totals and a mobile legend when inline labels don't fit.
// Extracted from UsageDashboard.tsx; slices carry the RAW subtype key so rate
// footnotes and colors are keyed on data, not display labels.

import React, { useState } from 'react';
import Pie, { ProvidedProps, PieArcDatum } from '@visx/shape/lib/shapes/Pie';
import { Group } from '@visx/group';
import { useTooltip, useTooltipInPortal } from '@visx/tooltip';
import { localPoint } from '@visx/event';
import {
    animated,
    useTransition,
    interpolate,
    type SpringValue,
} from '@react-spring/web';
import { formatCredits } from '~/lib/formatCredits';
import {
    CHART_THEME,
    USAGE_TOOLTIP_STYLES,
} from '~/lib/usage';

export interface PieDatum {
    /** Raw usage_type / usage_subtype key — colors key off this. */
    key: string;
    label: string;
    value: number;
    color: string;
    percentage: string; // Pre-calculated for performance
}

export interface UsagePieChartProps {
    data: PieDatum[];
    width: number;
    height: number;
    margin?: { top: number; right: number; bottom: number; left: number };
    title: string;
    showLabels?: boolean;
}

type AnimatedStyles = { startAngle: number; endAngle: number; opacity: number };

// @react-spring/web 9's intrinsic SVG aliases predate React 19's split SVG
// attribute types. Keep the compatibility shim at the library boundary while
// preserving precise animated values for the two elements used here.
const AnimatedPath = animated.path as unknown as React.ComponentType<
    Omit<React.SVGProps<SVGPathElement>, 'd'> & {
        d: ReturnType<typeof interpolate>;
    }
>;
const AnimatedGroup = animated.g as unknown as React.ComponentType<
    React.PropsWithChildren<
        Omit<React.SVGProps<SVGGElement>, 'style'> & {
            style: { opacity: SpringValue<number> };
        }
    >
>;

const fromLeaveTransition = ({ endAngle }: PieArcDatum<PieDatum>) => ({
    startAngle: endAngle > Math.PI ? 2 * Math.PI : 0,
    endAngle: endAngle > Math.PI ? 2 * Math.PI : 0,
    opacity: 0,
});

const enterUpdateTransition = ({
    startAngle,
    endAngle,
}: PieArcDatum<PieDatum>) => ({
    startAngle,
    endAngle,
    opacity: 1,
});

type AnimatedPieProps = ProvidedProps<PieDatum> & {
    animate?: boolean;
    getKey: (d: PieArcDatum<PieDatum>) => string;
    getColor: (d: PieArcDatum<PieDatum>) => string;
    onHover: (
        d: PieArcDatum<PieDatum> | null,
        event?: React.MouseEvent
    ) => void;
    hoveredSlice: PieArcDatum<PieDatum> | null;
    showLabels?: boolean;
};

function AnimatedPieSlices({
    animate = true,
    arcs,
    path,
    getKey,
    getColor,
    onHover,
    hoveredSlice,
    showLabels = true,
}: AnimatedPieProps) {
    const transitions = useTransition<PieArcDatum<PieDatum>, AnimatedStyles>(
        arcs,
        {
            from: animate ? fromLeaveTransition : enterUpdateTransition,
            enter: enterUpdateTransition,
            update: enterUpdateTransition,
            leave: animate ? fromLeaveTransition : enterUpdateTransition,
            keys: getKey,
        }
    );

    return transitions((props, arc, { key }) => {
        const [centroidX, centroidY] = path.centroid(arc);
        const hasSpaceForLabel = arc.endAngle - arc.startAngle >= 0.1;
        const isHovered = hoveredSlice && getKey(hoveredSlice) === getKey(arc);

        return (
            <g
                key={key}
                onMouseEnter={(event) => onHover(arc, event)}
                onMouseLeave={() => onHover(null)}
                onMouseMove={(event) => onHover(arc, event)}
                style={{ cursor: 'pointer' }}
            >
                <AnimatedPath
                    d={interpolate(
                        [props.startAngle, props.endAngle],
                        (startAngle, endAngle) =>
                            path({
                                ...arc,
                                startAngle,
                                endAngle,
                            }) ?? ''
                    )}
                    fill={getColor(arc)}
                    opacity={isHovered ? 1.0 : 0.85}
                    style={{ transition: 'opacity 0.2s ease' }}
                />
                {showLabels && hasSpaceForLabel && (
                    <AnimatedGroup style={{ opacity: props.opacity }}>
                        <text
                            fill="white"
                            x={centroidX}
                            y={centroidY}
                            dy=".33em"
                            fontSize={10}
                            textAnchor="middle"
                            pointerEvents="none"
                            fontWeight={500}
                        >
                            {arc.data.label}
                        </text>
                    </AnimatedGroup>
                )}
            </g>
        );
    });
}

export const UsagePieChart = React.memo(function UsagePieChart({
    data,
    width,
    height,
    margin = { top: 20, right: 20, bottom: 20, left: 20 },
    title,
    showLabels = true,
}: UsagePieChartProps) {
    // On mobile (showLabels=false) render a square SVG so the donut fills the space evenly
    const effectiveHeight = !showLabels ? Math.min(width, height) : height;
    const [hoveredSlice, setHoveredSlice] =
        useState<PieArcDatum<PieDatum> | null>(null);

    const {
        tooltipOpen,
        tooltipLeft,
        tooltipTop,
        tooltipData,
        hideTooltip,
        showTooltip,
    } = useTooltip<PieDatum>();

    const { containerRef, TooltipInPortal } = useTooltipInPortal({
        scroll: true,
    });

    if (width < 10 || !data.length) return null;

    const innerWidth = width - margin.left - margin.right;
    const innerHeight = effectiveHeight - margin.top - margin.bottom;
    const radius = Math.min(innerWidth, innerHeight) / 2;
    const centerY = innerHeight / 2;
    const centerX = innerWidth / 2;
    const donutThickness = Math.min(80, radius * 0.45);

    const handleHover = (
        arc: PieArcDatum<PieDatum> | null,
        event?: React.MouseEvent
    ) => {
        setHoveredSlice(arc);
        if (arc && event) {
            const coords = localPoint(event);
            showTooltip({
                tooltipData: arc.data,
                tooltipLeft: coords?.x,
                tooltipTop: coords?.y,
            });
        } else {
            hideTooltip();
        }
    };

    return (
        <div style={{ position: 'relative' }} ref={containerRef}>
            <svg
                width={width}
                height={effectiveHeight}
                style={{ display: 'block' }}
            >
                <rect
                    x={0}
                    y={0}
                    width={width}
                    height={effectiveHeight}
                    fill={CHART_THEME.background}
                    rx={8}
                />
                <Group top={centerY + margin.top} left={centerX + margin.left}>
                    <Pie
                        data={data}
                        pieValue={(d) => d.value}
                        outerRadius={radius}
                        innerRadius={radius - donutThickness}
                        cornerRadius={3}
                        padAngle={0.01}
                    >
                        {(pie) => (
                            <AnimatedPieSlices
                                {...pie}
                                animate={true}
                                getKey={(arc) => arc.data.key}
                                getColor={(arc) => arc.data.color}
                                onHover={handleHover}
                                hoveredSlice={hoveredSlice}
                                showLabels={showLabels}
                            />
                        )}
                    </Pie>

                    {/* Center text */}
                    <text
                        textAnchor="middle"
                        fill={CHART_THEME.text}
                        fontSize={14}
                        fontWeight={600}
                        y={-10}
                    >
                        {title}
                    </text>
                    <text
                        textAnchor="middle"
                        fill={CHART_THEME.textMuted}
                        fontSize={20}
                        fontWeight={700}
                        y={15}
                    >
                        {formatCredits(
                            hoveredSlice
                                ? hoveredSlice.data.value
                                : data.reduce((sum, d) => sum + d.value, 0)
                        )}
                    </text>
                    {hoveredSlice && (
                        <text
                            textAnchor="middle"
                            fill={CHART_THEME.textMuted}
                            fontSize={11}
                            y={30}
                        >
                            {hoveredSlice.data.label}
                        </text>
                    )}
                </Group>
            </svg>

            {tooltipOpen && tooltipData && (
                <TooltipInPortal
                    top={tooltipTop}
                    left={tooltipLeft}
                    style={USAGE_TOOLTIP_STYLES}
                >
                    <div>
                        <strong>{tooltipData.label}</strong>
                    </div>
                    <div style={{ marginTop: '4px', color: tooltipData.color }}>
                        {formatCredits(tooltipData.value)}
                    </div>
                    <div
                        style={{
                            marginTop: '4px',
                            fontSize: '10px',
                            color: CHART_THEME.textMuted,
                        }}
                    >
                        {tooltipData.percentage}% of total
                    </div>
                </TooltipInPortal>
            )}

            {/* Legend below chart when inline labels are hidden (mobile) */}
            {!showLabels && (
                <div
                    style={{
                        marginTop: '12px',
                        paddingLeft: '8px',
                        paddingRight: '8px',
                    }}
                >
                    <div
                        style={{
                            display: 'flex',
                            flexDirection: 'column',
                            gap: '6px',
                        }}
                    >
                        {data.map((d) => (
                            <div
                                key={d.key}
                                style={{
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: '8px',
                                }}
                            >
                                <div
                                    style={{
                                        width: 10,
                                        height: 10,
                                        borderRadius: 2,
                                        backgroundColor: d.color,
                                        flexShrink: 0,
                                    }}
                                />
                                <span
                                    style={{
                                        fontSize: '11px',
                                        color: CHART_THEME.textMuted,
                                        flex: 1,
                                        minWidth: 0,
                                        overflow: 'hidden',
                                        textOverflow: 'ellipsis',
                                        whiteSpace: 'nowrap',
                                    }}
                                >
                                    {d.label}
                                </span>
                                <span
                                    style={{
                                        fontSize: '11px',
                                        color: CHART_THEME.text,
                                        fontFamily: 'monospace',
                                        flexShrink: 0,
                                    }}
                                >
                                    {d.percentage}%
                                </span>
                            </div>
                        ))}
                    </div>
                </div>
            )}
        </div>
    );
});
