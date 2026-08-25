// Mini sticky note preview component for FlowHelperView and drag overlays.
// Renders a small sticky note that looks like an actual sticky note with text lines and corner fold.

interface MiniStickyNotePreviewProps {
    size: number;
}

export const MiniStickyNotePreview = ({ size }: MiniStickyNotePreviewProps) => {
    return (
        <div className="relative flex items-center justify-center">
            <div
                className="group relative rounded-lg overflow-hidden shadow-lg transition-all duration-300"
                style={{
                    width: size,
                    height: size,
                    backgroundColor: 'hsl(var(--card) / 0.9)',
                    border: '2px solid hsl(var(--muted-foreground) / 0.5)',
                }}
            >
                {/* Thick lines to simulate text */}
                <div className="absolute inset-x-4 top-5 bottom-4 flex flex-col gap-2 opacity-60">
                    <div className="h-1.5 rounded-full w-[85%]" style={{ backgroundColor: 'hsl(var(--foreground) / 0.9)' }} />
                    <div className="h-1.5 rounded-full w-[70%]" style={{ backgroundColor: 'hsl(var(--foreground) / 0.9)' }} />
                    <div className="h-1.5 rounded-full w-[90%]" style={{ backgroundColor: 'hsl(var(--foreground) / 0.9)' }} />
                    <div className="h-1.5 rounded-full w-[60%]" style={{ backgroundColor: 'hsl(var(--foreground) / 0.9)' }} />
                </div>

                {/* Corner fold effect (top-right) */}
                <div
                    className="absolute top-0 right-0 w-0 h-0 pointer-events-none"
                    style={{
                        borderStyle: 'solid',
                        borderWidth: '0 14px 14px 0',
                        borderColor: 'transparent hsl(var(--muted-foreground) / 0.5) transparent transparent',
                        opacity: 0.5,
                    }}
                />

                {/* Hover effect - subtle glow */}
                <div className="absolute inset-0 bg-foreground/0 group-hover:bg-foreground/5 transition-all duration-300" />
            </div>
        </div>
    );
};
