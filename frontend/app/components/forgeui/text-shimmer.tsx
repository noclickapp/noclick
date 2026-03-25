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
        backgroundImage: `linear-gradient(90deg, #71717a calc(50% - ${dynamicSpread}px), #ffffff, #71717a calc(50% + ${dynamicSpread}px)), linear-gradient(#71717a, #71717a)`,
      }}
    >
      {children}
    </MotionComponent>
  );
};

export default React.memo(TextShimmer);
