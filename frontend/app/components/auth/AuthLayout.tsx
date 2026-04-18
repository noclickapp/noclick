// AuthLayout component provides consistent layout for all authentication pages
// Includes split-screen design with form on left and cosmic visuals on right

import { ReactNode } from 'react';
import { ParticlesBackground } from '~/components/utils/ParticlesBackground';
import { motion } from 'framer-motion';

interface AuthLayoutProps {
    children: ReactNode;
    showRightPanel?: boolean;
    quote?: {
        text: string;
        author: string;
    };
}

export function AuthLayout({ 
    children, 
    showRightPanel = true,
    quote = {
        text: "We're supposed to look up and wonder at our place in the stars, not look down and worry about our place in the dirt.",
        author: "Cooper, Interstellar"
    }
}: AuthLayoutProps) {
    return (
        <div className="min-h-screen flex bg-black">
            {/* Left side - Auth Form */}
            <div className="flex-1 flex items-center justify-center px-8 sm:px-12 lg:px-16 bg-zinc-950">
                <div className="w-full max-w-md relative z-10">
                    {children}
                </div>
            </div>

            {/* Right side - Banner with Stars and Black Hole */}
            {showRightPanel && (
                <div className="hidden lg:block lg:w-1/2 xl:w-[55%] relative overflow-hidden bg-black border-l border-zinc-800">
                    {/* Quote in top-left */}
                    <div className="absolute top-20 left-20 z-20 max-w-md">
                        <p className="text-white text-3xl font-bold leading-tight tracking-tight mb-3">
                            "{quote.text}"
                        </p>
                        <p className="text-white/70 text-lg">— {quote.author}</p>
                    </div>
                    
                    {/* Black hole image - aligned flush with right edge */}
                    <img
                        src="/blackhole.webp"
                        alt="Black hole visualization"
                        className="absolute right-0 top-1/2 -translate-y-1/2 h-[65vh] w-auto object-contain opacity-80 rr-block"
                    />
                    
                    {/* Particle effects on top - contained within this div */}
                    <div className="absolute inset-0 pointer-events-none overflow-hidden">
                        <ParticlesBackground count={300} starOpacity={0.8} className="absolute inset-0" />
                    </div>
                </div>
            )}
        </div>
    );
}