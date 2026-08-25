import { useEffect, useRef, useState } from 'react';
import { cn } from '~/lib/utils';

interface CustomAudioVisualizerProps {
    orientation?: 'vertical' | 'horizontal';
    width: number;
    height: number;
    barWidth?: number;
    barGap?: number;
    /** Whether the visualizer is actively recording (replaces VAD-based isSpeaking) */
    isActive: boolean;
    onClick?: () => void;
    className?: string;
    useContainerWidth?: boolean;
}

export function CustomAudioVisualizer({
    orientation = 'horizontal',
    width,
    height,
    barWidth = 3,
    barGap = 2,
    isActive,
    onClick,
    className,
    useContainerWidth = false,
}: CustomAudioVisualizerProps) {
    const containerRef = useRef<HTMLDivElement>(null);
    const [bars, setBars] = useState<number[]>([]);

    useEffect(() => {
        if (!containerRef.current) return;

        const updateBars = () => {
            const container = containerRef.current;
            if (!container) return;

            const currentWidth = useContainerWidth
                ? container.clientWidth
                : width;

            const totalBars = Math.floor(currentWidth / (barWidth + barGap));
            setBars(Array.from({ length: totalBars }, () => 0.15));
        };

        updateBars();

        if (useContainerWidth) {
            const resizeObserver = new ResizeObserver(updateBars);
            resizeObserver.observe(containerRef.current);
            return () => resizeObserver.disconnect();
        }
    }, [width, height, barWidth, barGap, orientation, useContainerWidth]);

    useEffect(() => {
        const intervalId = setInterval(() => {
            setBars((prevBars) => {
                const newBars = [...prevBars];
                // When active, show more animated bars (simulates voice activity)
                const maxHeight = isActive ? 0.75 : 0.3;
                const minHeight = 0.15;
                newBars[0] =
                    Math.random() * (maxHeight - minHeight) + minHeight;

                for (let i = 1; i < newBars.length; i++) {
                    const prevHeight = newBars[i - 1];
                    const randomHeight = Math.random() * (maxHeight / 2);
                    newBars[i] = prevHeight * 0.5 + randomHeight;
                    newBars[i] = Math.max(
                        minHeight,
                        Math.min(maxHeight, newBars[i])
                    );
                }
                return newBars;
            });
        }, 125);

        return () => clearInterval(intervalId);
    }, [isActive]);

    return (
        // eslint-disable-next-line jsx-a11y/click-events-have-key-events, jsx-a11y/no-static-element-interactions
        <div
            ref={containerRef}
            className={cn(
                'relative flex items-center justify-center',
                orientation === 'horizontal' ? 'flex-row' : 'flex-col',
                className
            )}
            style={{
                width: useContainerWidth ? '100%' : width,
                height,
                gap: barGap,
                cursor: onClick ? 'pointer' : 'default',
            }}
            onClick={onClick}
        >
            {bars.map((barHeight, index) => (
                <div
                    key={index}
                    className="bg-white rounded-full"
                    style={{
                        width:
                            orientation === 'horizontal'
                                ? barWidth
                                : `${barHeight * 100}%`,
                        height:
                            orientation === 'horizontal'
                                ? `${barHeight * 100}%`
                                : barWidth,
                        opacity: isActive ? 1 : 0.5,
                        transition: 'all 125ms ease-out',
                    }}
                />
            ))}
        </div>
    );
}
