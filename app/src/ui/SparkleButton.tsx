// SparkleButton — emits a radial burst of particles from the button edges on click,
// with an optional animated icon (check/cross) that replaces the label momentarily.

import { useState, useRef, useCallback } from 'react';

interface Spark {
    id: number;
    x: number;
    y: number;
    color: string;
    size: number;
    angle: number;
    distance: number;
    delay: number;
}

let sparkId = 0;

const DEFAULT_COLORS_LIGHT = ['#ffffff', '#e4e4e7', '#d4d4d8', '#fafafa'];
const DEFAULT_COLORS_DARK = ['#a1a1aa', '#d4d4d8', '#71717a', '#a1a1aa'];

interface SparkleButtonProps {
    onClick: () => void;
    className?: string;
    children: React.ReactNode;
    /** Color preset: 'light' for white sparks, 'dark' for gray sparks, or custom array */
    sparkColors?: 'light' | 'dark' | string[];
    /** Number of particles (default: 20) */
    particleCount?: number;
    /** Show an animated icon on click: 'check' for approve, 'cross' for reject */
    feedbackIcon?: 'check' | 'cross';
}

// Animated check — circle draws in, then tick strokes
function AnimatedCheck({ color = '#000' }: { color?: string }) {
    return (
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" className="animated-feedback-icon">
            <circle cx="12" cy="12" r="10" stroke={color} strokeWidth="2" fill="none"
                strokeDasharray="63" strokeDashoffset="63"
                style={{ animation: 'circle-draw 300ms ease-out forwards' }} />
            <path d="M8 12.5l2.5 2.5 5.5-5.5" stroke={color} strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"
                fill="none" strokeDasharray="15" strokeDashoffset="15"
                style={{ animation: 'check-draw 250ms ease-out 200ms forwards' }} />
        </svg>
    );
}

// Animated cross — circle draws in, then X strokes
function AnimatedCross({ color = '#a1a1aa' }: { color?: string }) {
    return (
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" className="animated-feedback-icon">
            <circle cx="12" cy="12" r="10" stroke={color} strokeWidth="2" fill="none"
                strokeDasharray="63" strokeDashoffset="63"
                style={{ animation: 'circle-draw 300ms ease-out forwards' }} />
            <path d="M9 9l6 6M15 9l-6 6" stroke={color} strokeWidth="2.5" strokeLinecap="round"
                fill="none" strokeDasharray="17" strokeDashoffset="17"
                style={{ animation: 'check-draw 250ms ease-out 200ms forwards' }} />
        </svg>
    );
}

export function SparkleButton({
    onClick,
    className = '',
    children,
    sparkColors = 'light',
    particleCount = 20,
    feedbackIcon,
}: SparkleButtonProps) {
    const ref = useRef<HTMLButtonElement>(null);
    const [sparks, setSparks] = useState<Spark[]>([]);
    const [showIcon, setShowIcon] = useState(false);

    const colors = Array.isArray(sparkColors)
        ? sparkColors
        : sparkColors === 'light' ? DEFAULT_COLORS_LIGHT : DEFAULT_COLORS_DARK;

    const handleClick = useCallback(() => {
        const el = ref.current;
        if (!el) return;

        const w = el.offsetWidth;
        const h = el.offsetHeight;

        const newSparks: Spark[] = Array.from({ length: particleCount }, () => {
            const edge = Math.floor(Math.random() * 4);
            let x: number, y: number, angle: number;

            switch (edge) {
                case 0:
                    x = Math.random() * w; y = 0;
                    angle = -90 + (Math.random() - 0.5) * 60; break;
                case 1:
                    x = w; y = Math.random() * h;
                    angle = 0 + (Math.random() - 0.5) * 60; break;
                case 2:
                    x = Math.random() * w; y = h;
                    angle = 90 + (Math.random() - 0.5) * 60; break;
                default:
                    x = 0; y = Math.random() * h;
                    angle = 180 + (Math.random() - 0.5) * 60; break;
            }

            return {
                id: ++sparkId, x, y,
                color: colors[Math.floor(Math.random() * colors.length)],
                size: 2 + Math.random() * 2.5,
                angle,
                distance: 30 + Math.random() * 40,
                delay: Math.random() * 80,
            };
        });

        setSparks(newSparks);
        setTimeout(() => setSparks([]), 700);

        if (feedbackIcon) {
            setShowIcon(true);
            setTimeout(() => setShowIcon(false), 700);
        }

        onClick();
    }, [onClick, colors, particleCount, feedbackIcon]);

    return (
        <button ref={ref} onClick={handleClick} className={`${className} relative`}>
            {/* Label / icon crossfade */}
            <span className={`inline-flex items-center gap-1 transition-opacity duration-150 ${showIcon ? 'opacity-0' : 'opacity-100'}`}>
                {children}
            </span>
            {showIcon && feedbackIcon && (
                <span className="absolute inset-0 flex items-center justify-center">
                    {feedbackIcon === 'check'
                        ? <AnimatedCheck color="currentColor" />
                        : <AnimatedCross color="currentColor" />
                    }
                </span>
            )}

            {/* Sparkle particles */}
            {sparks.length > 0 && (
                <span className="absolute inset-0 pointer-events-none overflow-visible" aria-hidden>
                    {sparks.map(spark => (
                        <span
                            key={spark.id}
                            className="absolute rounded-full"
                            style={{
                                width: spark.size,
                                height: spark.size,
                                backgroundColor: spark.color,
                                left: spark.x,
                                top: spark.y,
                                boxShadow: `0 0 ${spark.size}px ${spark.color}`,
                                animation: `sparkle-fly 500ms ease-out ${spark.delay}ms both`,
                                '--spark-x': `${Math.cos(spark.angle * Math.PI / 180) * spark.distance}px`,
                                '--spark-y': `${Math.sin(spark.angle * Math.PI / 180) * spark.distance}px`,
                            } as React.CSSProperties}
                        />
                    ))}
                </span>
            )}
        </button>
    );
}
