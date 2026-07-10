// Animated text shimmer component using framer-motion.
// Adapted from @forgeui/text-shimmer for Tailwind v3 compatibility.

"use client";

import { cn } from "~/lib/utils";
import { motion } from "framer-motion";
import React, { useMemo } from "react";

export type TextShimmerProps = {
  children: string;
  as?: React.ElementType;
  className?: string;
  duration?: number;
  spread?: number;
};

const TextShimmer = ({
  children,
  as: Component = "span",
  className,
  duration = 2,
  spread = 2,
}: TextShimmerProps) => {
  const MotionComponent = motion(Component as any);

  const dynamicSpread = useMemo(() => {
    return children.length * spread;
  }, [children, spread]);

  return (
    <MotionComponent
      className={cn("relative inline-block bg-clip-text text-transparent", className)}
      initial={{ backgroundPosition: "100% center" }}
      animate={{ backgroundPosition: "0% center" }}
      transition={{
        repeat: Infinity,
        duration,
        ease: "linear",
      }}
      style={{
        backgroundSize: "250% 100%",
        backgroundRepeat: "no-repeat",
        // Theme-adaptive via the shared pulse tokens: a soft charcoal crest sweeps
        // a readable gray base in light mode, a white gleam in dark. A hardcoded
        // #fff crest erased the letters on the light card.
        backgroundImage: `linear-gradient(90deg, hsl(var(--pulse-base)) calc(50% - ${dynamicSpread}px), hsl(var(--pulse-crest)), hsl(var(--pulse-base)) calc(50% + ${dynamicSpread}px)), linear-gradient(hsl(var(--pulse-base)), hsl(var(--pulse-base)))`,
      }}
    >
      {children}
    </MotionComponent>
  );
};

export default React.memo(TextShimmer);
