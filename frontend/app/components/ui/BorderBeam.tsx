"use client";

import { cn } from "~/lib/utils";

interface BorderBeamProps {
  className?: string;
  duration?: number;
  borderWidth?: number;
  colorFrom?: string;
  colorTo?: string;
  delay?: number;
  size?: number;
}

export function BorderBeam({
  className,
  duration = 6,
  borderWidth = 1.5,
  colorFrom = "transparent",
  colorTo = "white",
  delay = 0,
  size = 150,
}: BorderBeamProps) {
  return (
    <div
      className={cn(
        "pointer-events-none absolute inset-0 rounded-[inherit]",
        className
      )}
      style={{
        padding: borderWidth,
        // Use mask to only show the border area
        WebkitMask: `
          linear-gradient(#fff 0 0) content-box,
          linear-gradient(#fff 0 0)
        `,
        WebkitMaskComposite: "xor",
        mask: `
          linear-gradient(#fff 0 0) content-box,
          linear-gradient(#fff 0 0)
        `,
        maskComposite: "exclude",
      }}
    >
      {/* First beam */}
      <div
        className="absolute"
        style={{
          width: size,
          height: size,
          background: `radial-gradient(circle, ${colorTo} 0%, ${colorFrom} 40%, transparent 55%)`,
          offsetPath: `rect(0 100% 100% 0 round 16px)`,
          animation: `border-beam ${duration}s linear infinite`,
          animationDelay: `${delay}s`,
        }}
      />
      {/* Second beam - opposite side */}
      <div
        className="absolute"
        style={{
          width: size,
          height: size,
          background: `radial-gradient(circle, ${colorTo} 0%, ${colorFrom} 40%, transparent 55%)`,
          offsetPath: `rect(0 100% 100% 0 round 16px)`,
          animation: `border-beam ${duration}s linear infinite`,
          animationDelay: `${delay - duration / 2}s`,
        }}
      />
    </div>
  );
}
