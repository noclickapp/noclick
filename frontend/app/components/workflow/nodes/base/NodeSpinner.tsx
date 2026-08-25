// Reusable spinner component that wraps around node content (icons, text, etc.)
// When loading, displays a rotating ring around the children and scales them down to fit inside.

import { ReactNode } from 'react';

const spinnerStyles = `
@keyframes spin-smooth {
    from {
        transform: translate(-50%, -50%) rotate(0deg);
    }
    to {
        transform: translate(-50%, -50%) rotate(360deg);
    }
}
.spinner-ring {
    animation: spin-smooth 2s linear infinite;
}
`;

interface NodeSpinnerProps {
    isLoading: boolean;
    children: ReactNode;
    spinnerRadius?: number; // Radius of the spinner circle from center (default: 35)
}

export const NodeSpinner = ({ isLoading, children, spinnerRadius = 35 }: NodeSpinnerProps) => {
    const diameter = spinnerRadius * 2;

    return (
        <>
            <style>{spinnerStyles}</style>
            <div className="relative inline-flex items-center justify-center">
                {/* Children - scale down when loading to fit inside spinner ring */}
                <div
                    className="relative z-10 transition-transform duration-300 ease-out"
                    style={{
                        transform: isLoading ? 'scale(0.78)' : 'scale(1)'
                    }}
                >
                    {children}
                </div>

                {/* Spinner ring - overlays and rotates when loading */}
                {isLoading && (
                    <svg
                        className="absolute spinner-ring"
                        width={diameter}
                        height={diameter}
                        viewBox="0 0 100 100"
                        style={{
                            pointerEvents: 'none',
                            left: '50%',
                            top: '50%',
                        }}
                    >
                        <circle
                            cx="50"
                            cy="50"
                            r="45"
                            fill="none"
                            style={{ stroke: 'hsl(var(--foreground))' }}
                            strokeWidth="4.5"
                            strokeDasharray="90 150"
                            strokeLinecap="round"
                            opacity="0.7"
                        />
                    </svg>
                )}
            </div>
        </>
    );
};
