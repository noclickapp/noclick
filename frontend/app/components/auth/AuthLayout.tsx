// AuthLayout component provides consistent layout for all authentication pages
// Includes split-screen design with form on left and cosmic visuals on right

import { ReactNode, useEffect, useRef, useState } from 'react';
import { ParticlesBackground } from '~/components/utils/ParticlesBackground';
import { useMediaQuery } from '~/hooks/useIsMobile';
import { useIdleReady } from '~/hooks/useIdleReady';

type NetworkInformation = EventTarget & {
    saveData?: boolean;
    effectiveType?: string;
};

function useConstrainedNetwork(): boolean {
    const [constrained, setConstrained] = useState(false);

    useEffect(() => {
        const connection = (
            navigator as Navigator & { connection?: NetworkInformation }
        ).connection;
        if (!connection) return;

        const update = () =>
            setConstrained(
                connection.saveData === true ||
                connection.effectiveType === 'slow-2g' ||
                connection.effectiveType === '2g'
            );
        update();
        connection.addEventListener('change', update);
        return () => connection.removeEventListener('change', update);
    }, []);

    return constrained;
}

function DeferredBlackHoleVideo({ className }: { className: string }) {
    const videoRef = useRef<HTMLVideoElement>(null);
    const [playing, setPlaying] = useState(false);

    const tryPlay = () => {
        const video = videoRef.current;
        if (!video || document.visibilityState !== 'visible') return;
        video.muted = true;
        void video.play().catch(() => {
            // Keep showing the exact-frame poster if the browser blocks autoplay.
        });
    };

    useEffect(() => {
        const handleVisibilityChange = () => {
            if (document.visibilityState === 'visible') tryPlay();
        };
        document.addEventListener('visibilitychange', handleVisibilityChange);
        tryPlay();
        return () =>
            document.removeEventListener('visibilitychange', handleVisibilityChange);
    }, []);

    return (
        <video
            ref={videoRef}
            aria-label="Slowly rotating black hole visualization"
            autoPlay
            loop
            muted
            playsInline
            preload="metadata"
            poster="/video/blackhole-first-frame.webp"
            onCanPlay={tryPlay}
            onPlaying={() => setPlaying(true)}
            onPause={() => setPlaying(false)}
            className={`${className} transition-opacity duration-300 ${
                playing ? 'opacity-90' : 'opacity-0'
            }`}
        >
            <source
                src="/video/blackhole-3x.av1.mp4"
                type='video/mp4; codecs="av01.0.05M.10"'
            />
            <source src="/video/blackhole-3x.mp4" type="video/mp4" />
        </video>
    );
}

interface AuthLayoutProps {
    children: ReactNode;
    showRightPanel?: boolean;
    quote?: {
        text: string;
        author: string;
    };
    /** Replaces the default cosmic black-hole art in the right panel (e.g. the
        agent-scaffold preview when a visitor arrives from an /agents SEO CTA). */
    rightPanel?: ReactNode;
}

export function AuthLayout({
    children,
    showRightPanel = true,
    quote = {
        text: "We're supposed to look up and wonder at our place in the stars, not look down and worry about our place in the dirt.",
        author: "Cooper, Interstellar"
    },
    rightPanel
}: AuthLayoutProps) {
    // Keep media URLs out of the server-rendered video markup. The video is
    // mounted only after hydration, only when its desktop panel is visible,
    // and only after critical page work has had a chance to finish.
    const desktopPanelVisible = useMediaQuery('(min-width: 1024px)');
    const idleReady = useIdleReady(1500);
    const constrainedNetwork = useConstrainedNetwork();
    const shouldLoadVideo =
        desktopPanelVisible && idleReady && !constrainedNetwork;
    const blackHoleClassName =
        'absolute -right-[77%] xl:-right-[67%] top-[57%] -translate-y-1/2 -rotate-[9deg] w-[70vw] xl:w-[66vw] max-w-[1470px] h-auto object-contain rr-block ph-no-capture';

    return (
        <div className="min-h-screen flex bg-background">
            {/* Left side - Auth Form */}
            <div className="flex-1 flex items-center justify-center px-8 sm:px-12 lg:px-16 bg-sunken">
                <div className="w-full max-w-md relative z-10">
                    {children}
                </div>
            </div>

            {/* Right side - agent-scaffold preview (if supplied) or cosmic banner */}
            {showRightPanel && (
                <div
                    className={`hidden lg:block relative overflow-hidden bg-black border-l border-border ${
                        !rightPanel
                            ? 'lg:w-[45%]'
                            : 'lg:w-1/2 xl:w-[55%]'
                    }`}
                >
                    {rightPanel ? (
                        rightPanel
                    ) : (
                        <>
                            {/* Quote in top-left */}
                            <div className="absolute top-20 left-20 z-20 max-w-md">
                                <p className="text-white text-3xl font-bold leading-tight tracking-tight mb-3">
                                    &ldquo;{quote.text}&rdquo;
                                </p>
                                <p className="text-white/70 text-lg">— {quote.author}</p>
                            </div>

                            {/* Black hole art - oversized, angled, and partially off-canvas */}
                            <picture>
                                <source
                                    media="(min-width: 1024px)"
                                    srcSet="/video/blackhole-first-frame.webp"
                                    type="image/webp"
                                />
                                <img
                                    src="data:image/gif;base64,R0lGODlhAQABAAD/ACwAAAAAAQABAAACADs="
                                    alt="Black hole visualization"
                                    width={1470}
                                    height={630}
                                    decoding="async"
                                    fetchPriority="high"
                                    className={`${blackHoleClassName} opacity-90`}
                                />
                            </picture>
                            {shouldLoadVideo && (
                                <DeferredBlackHoleVideo className={blackHoleClassName} />
                            )}

                            {/* Particle effects on top - contained within this div */}
                            <div className="absolute inset-0 pointer-events-none overflow-hidden">
                                <ParticlesBackground starOpacity={0.8} className="absolute inset-0" />
                            </div>
                        </>
                    )}
                </div>
            )}
        </div>
    );
}
