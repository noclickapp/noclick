/**
 * Reusable canvas-based confetti effect component.
 * Renders a burst of animated confetti particles with physics simulation.
 * Can be triggered from anywhere by changing the `trigger` prop.
 *
 * Usage:
 *   const [showConfetti, setShowConfetti] = useState(false);
 *   <Confetti trigger={showConfetti} onComplete={() => setShowConfetti(false)} />
 */

import { useEffect, useRef, useCallback } from 'react';

interface ConfettiProps {
    /** Increment this value to trigger a new confetti burst */
    trigger: number;
    /** Called when the confetti animation completes */
    onComplete?: () => void;
    /** Number of particles to spawn (default: 100) */
    particleCount?: number;
    /** Duration in milliseconds (default: 3000) */
    duration?: number;
    /** Colors for confetti particles (default: rainbow) */
    colors?: string[];
    /** Origin point as { x: 0-1, y: 0-1 } relative to viewport (default: { x: 0.5, y: 0.5 }) */
    origin?: { x: number; y: number };
    /** Spread angle in degrees (default: 360 for full burst) */
    spread?: number;
    /** Direction angle in degrees (0 = right, 90 = down, 180 = left, 270 = up). Default: 270 (up) */
    angle?: number;
    /** Initial velocity range (default: { min: 8, max: 15 }) */
    velocity?: { min: number; max: number };
    /** Z-index for the canvas overlay (default: 9999) */
    zIndex?: number;
}

interface Particle {
    x: number;
    y: number;
    vx: number;
    vy: number;
    color: string;
    size: number;
    rotation: number;
    rotationSpeed: number;
    shape: 'rect' | 'circle' | 'strip';
    opacity: number;
    gravity: number;
    drag: number;
}

const DEFAULT_COLORS = [
    '#FF6B6B', // Red
    '#4ECDC4', // Teal
    '#45B7D1', // Blue
    '#96CEB4', // Green
    '#FFEAA7', // Yellow
    '#DDA0DD', // Plum
    '#98D8C8', // Mint
    '#F7DC6F', // Gold
    '#BB8FCE', // Purple
    '#85C1E9', // Light Blue
];

function createParticle(
    x: number,
    y: number,
    colors: string[],
    velocity: { min: number; max: number },
    spread: number,
    baseAngle: number
): Particle {
    // Convert base angle to radians and add random spread
    const baseAngleRad = baseAngle * (Math.PI / 180);
    const angle = baseAngleRad + (Math.random() * spread - spread / 2) * (Math.PI / 180);
    const speed = velocity.min + Math.random() * (velocity.max - velocity.min);
    const shapes: Particle['shape'][] = ['rect', 'circle', 'strip'];

    return {
        x,
        y,
        vx: Math.cos(angle) * speed,
        vy: Math.sin(angle) * speed,
        color: colors[Math.floor(Math.random() * colors.length)],
        size: 6 + Math.random() * 6,
        rotation: Math.random() * Math.PI * 2,
        rotationSpeed: (Math.random() - 0.5) * 0.3,
        shape: shapes[Math.floor(Math.random() * shapes.length)],
        opacity: 1,
        gravity: 0.25 + Math.random() * 0.1,
        drag: 0.98 + Math.random() * 0.015,
    };
}

function drawParticle(ctx: CanvasRenderingContext2D, particle: Particle) {
    ctx.save();
    ctx.translate(particle.x, particle.y);
    ctx.rotate(particle.rotation);
    ctx.globalAlpha = particle.opacity;
    ctx.fillStyle = particle.color;

    switch (particle.shape) {
        case 'rect':
            ctx.fillRect(-particle.size / 2, -particle.size / 4, particle.size, particle.size / 2);
            break;
        case 'circle':
            ctx.beginPath();
            ctx.arc(0, 0, particle.size / 3, 0, Math.PI * 2);
            ctx.fill();
            break;
        case 'strip':
            ctx.fillRect(-particle.size / 6, -particle.size, particle.size / 3, particle.size * 2);
            break;
    }

    ctx.restore();
}

function updateParticle(particle: Particle, deltaTime: number): boolean {
    // Apply physics with frame-rate independent calculations
    particle.vy += particle.gravity * deltaTime;
    const dragFactor = Math.pow(particle.drag, deltaTime); // Correct drag for variable frame rate
    particle.vx *= dragFactor;
    particle.vy *= dragFactor;
    particle.x += particle.vx * deltaTime;
    particle.y += particle.vy * deltaTime;
    particle.rotation += particle.rotationSpeed * deltaTime;

    // Return true if particle is still visible
    return particle.opacity > 0.01;
}

export function Confetti({
    trigger,
    onComplete,
    particleCount = 100,
    duration = 3000,
    colors = DEFAULT_COLORS,
    origin = { x: 0.5, y: 0.5 },
    spread = 360,
    angle = 270,
    velocity = { min: 8, max: 15 },
    zIndex = 9999,
}: ConfettiProps) {
    const canvasRef = useRef<HTMLCanvasElement>(null);
    const particlesRef = useRef<Particle[]>([]);
    const animationRef = useRef<number | null>(null);
    const startTimeRef = useRef<number>(0);
    const lastFrameTimeRef = useRef<number>(0);
    const lastTriggerRef = useRef<number>(0);

    const animate = useCallback(
        (currentTime: number) => {
            const canvas = canvasRef.current;
            if (!canvas) return;

            const ctx = canvas.getContext('2d');
            if (!ctx) return;

            const elapsed = currentTime - startTimeRef.current;
            const progress = Math.min(elapsed / duration, 1);

            // Clear canvas
            ctx.clearRect(0, 0, canvas.width, canvas.height);

            // Calculate frame-rate independent delta time (normalized to 60fps baseline)
            const frameTime = lastFrameTimeRef.current ? currentTime - lastFrameTimeRef.current : 16.67;
            lastFrameTimeRef.current = currentTime;
            const deltaTime = Math.min(frameTime / 16.67, 3); // Cap at 3x to prevent jumps on tab switch
            let activeParticles = 0;

            for (const particle of particlesRef.current) {
                // Fade out towards the end
                if (progress > 0.7) {
                    particle.opacity = Math.max(0, 1 - (progress - 0.7) / 0.3);
                }

                if (updateParticle(particle, deltaTime)) {
                    drawParticle(ctx, particle);
                    activeParticles++;
                }
            }

            // Continue animation if there are active particles and duration not exceeded
            if (activeParticles > 0 && progress < 1) {
                animationRef.current = requestAnimationFrame(animate);
            } else {
                // Animation complete
                ctx.clearRect(0, 0, canvas.width, canvas.height);
                particlesRef.current = [];
                onComplete?.();
            }
        },
        [duration, onComplete]
    );

    const startConfetti = useCallback(() => {
        const canvas = canvasRef.current;
        if (!canvas) return;

        // Set canvas size to window size
        canvas.width = window.innerWidth;
        canvas.height = window.innerHeight;

        // Calculate origin in pixels
        const originX = canvas.width * origin.x;
        const originY = canvas.height * origin.y;

        // Create particles
        particlesRef.current = Array.from({ length: particleCount }, () =>
            createParticle(originX, originY, colors, velocity, spread, angle)
        );

        // Start animation
        startTimeRef.current = performance.now();
        lastFrameTimeRef.current = 0; // Reset for fresh delta calculation
        if (animationRef.current) {
            cancelAnimationFrame(animationRef.current);
        }
        animationRef.current = requestAnimationFrame(animate);
    }, [particleCount, colors, origin, velocity, spread, angle, animate]);

    // Handle trigger changes
    // Note: startConfetti is intentionally excluded from deps - we only want to fire
    // when trigger changes, not when props change. The latest startConfetti is called
    // because it's accessed from the ref-like pattern of useCallback.
    useEffect(() => {
        if (trigger > 0 && trigger !== lastTriggerRef.current) {
            lastTriggerRef.current = trigger;
            startConfetti();
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [trigger]);

    // Handle window resize
    useEffect(() => {
        const handleResize = () => {
            const canvas = canvasRef.current;
            if (canvas && particlesRef.current.length > 0) {
                canvas.width = window.innerWidth;
                canvas.height = window.innerHeight;
            }
        };

        window.addEventListener('resize', handleResize);
        return () => window.removeEventListener('resize', handleResize);
    }, []);

    // Don't render if never triggered
    if (trigger === 0) return null;

    return (
        <canvas
            ref={canvasRef}
            className="pointer-events-none fixed inset-0"
            style={{ zIndex }}
            aria-hidden="true"
        />
    );
}

/**
 * Hook for managing confetti state.
 * Returns a trigger function and the current trigger count.
 *
 * Usage:
 *   const { trigger, fire } = useConfetti();
 *   <Confetti trigger={trigger} />
 *   // Later: fire();
 */
export function useConfetti() {
    const triggerRef = useRef(0);
    const setTriggerRef = useRef<(n: number) => void>(() => {});

    const fire = useCallback(() => {
        triggerRef.current += 1;
        setTriggerRef.current(triggerRef.current);
    }, []);

    return {
        trigger: triggerRef.current,
        fire,
        /** Pass this to a setState to enable re-renders */
        bindSetTrigger: (setter: (n: number) => void) => {
            setTriggerRef.current = setter;
        },
    };
}

/**
 * Preset configurations for common confetti effects.
 */
export const ConfettiPresets = {
    /** Celebration burst from center */
    celebration: {
        particleCount: 150,
        spread: 360,
        velocity: { min: 10, max: 18 },
        origin: { x: 0.5, y: 0.5 },
    },
    /** Firework burst from bottom */
    firework: {
        particleCount: 80,
        spread: 120,
        velocity: { min: 12, max: 20 },
        origin: { x: 0.5, y: 0.9 },
    },
    /** Subtle shower from top */
    shower: {
        particleCount: 60,
        spread: 180,
        velocity: { min: 3, max: 8 },
        origin: { x: 0.5, y: 0 },
    },
    /** Side cannon burst */
    cannon: {
        particleCount: 50,
        spread: 60,
        velocity: { min: 15, max: 25 },
        origin: { x: 0, y: 0.7 },
    },
} as const;
