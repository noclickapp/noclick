// Static SVG illustration shown at the top of the invite "find the link"
// walkthrough tooltip (GuidedTourHighlight), in place of a .webm video. It
// reuses InviteCard's visual language — the canvas dot-grid, the dark invite-link
// field beside a white Copy button, and the named collaborator cursors converging — to say
// "copy this link and people join your flow live." Composed to look complete
// with ZERO animation (the lone glow pulse is purely additive), so it renders
// correctly even when requestAnimationFrame/SMIL is paused (backgrounded tab).

export function InviteWalkthroughArt() {
    return (
        <div
            className="absolute inset-0 h-full w-full overflow-hidden"
            style={{
                backgroundColor: '#0c0c10',
                backgroundImage: 'radial-gradient(circle, rgba(255,255,255,0.08) 1px, transparent 1px)',
                backgroundSize: '13px 13px',
            }}
        >
            <svg viewBox="0 0 320 180" preserveAspectRatio="xMidYMid slice" className="absolute inset-0 h-full w-full" aria-hidden="true">
                <defs>
                    {/* vignette so the dot-grid fades at the edges, focusing the eye on center */}
                    <radialGradient id="cv-vignette" cx="50%" cy="46%" r="62%">
                        <stop offset="52%" stopColor="#0c0c10" stopOpacity="0" />
                        <stop offset="100%" stopColor="#0c0c10" stopOpacity="0.92" />
                    </radialGradient>
                    {/* white focal glow behind the invite-link pill (the single bright accent) */}
                    <radialGradient id="cv-glow" cx="50%" cy="50%" r="50%">
                        <stop offset="0%" stopColor="#ffffff" stopOpacity="0.26" />
                        <stop offset="38%" stopColor="#ffffff" stopOpacity="0.09" />
                        <stop offset="100%" stopColor="#ffffff" stopOpacity="0" />
                    </radialGradient>
                    {/* faint top sheen matching InviteCard's top radial */}
                    <radialGradient id="cv-top" cx="50%" cy="-10%" r="85%">
                        <stop offset="0%" stopColor="#ffffff" stopOpacity="0.06" />
                        <stop offset="55%" stopColor="#ffffff" stopOpacity="0" />
                    </radialGradient>
                    <filter id="cv-pill" x="-50%" y="-50%" width="200%" height="200%">
                        <feDropShadow dx="0" dy="2" stdDeviation="3" floodColor="#000000" floodOpacity="0.5" />
                    </filter>
                    <filter id="cv-cursor" x="-50%" y="-50%" width="200%" height="200%">
                        <feDropShadow dx="0" dy="1.4" stdDeviation="1.5" floodColor="#000000" floodOpacity="0.6" />
                    </filter>
                </defs>

                {/* background washes (dot-grid comes from the wrapper div) */}
                <rect x="0" y="0" width="320" height="180" fill="url(#cv-vignette)" />
                <rect x="0" y="0" width="320" height="180" fill="url(#cv-top)" />

                {/* focal glow behind the pill, centered on (160,86) */}
                <circle cx="160" cy="86" r="74" fill="url(#cv-glow)" />
                {/* additive-only bonus pulse: complete & beautiful when paused */}
                <circle cx="160" cy="86" r="74" fill="url(#cv-glow)" opacity="0">
                    <animate attributeName="opacity" values="0;0.5;0" dur="3.6s" repeatCount="indefinite" />
                </circle>

                {/* ===== center: invite-link field + Copy button — mirrors InviteCard's
                    real row (a dark bordered URL field beside a white Copy CTA) ===== */}
                {/* URL field — dark + bordered, like the real readonly input */}
                <g filter="url(#cv-pill)">
                    <rect x="72" y="72" width="114" height="28" rx="9" fill="#141419" stroke="#ffffff" strokeOpacity="0.22" strokeWidth="1" />
                    {/* faint inset sheen (echoes ring-inset ring-white/5) */}
                    <rect x="73.2" y="73.2" width="111.6" height="25.6" rx="8" fill="none" stroke="#ffffff" strokeOpacity="0.06" strokeWidth="1" />
                    {/* link glyph — lucide Link2 (light on dark), matching the real input's icon */}
                    <g transform="translate(85, 86) scale(0.5) translate(-12, -12)" stroke="#d4d4d8" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" fill="none">
                        <path d="M9 17H7A5 5 0 0 1 7 7h2" />
                        <path d="M15 7h2a5 5 0 1 1 0 10h-2" />
                        <line x1="8" y1="12" x2="16" y2="12" />
                    </g>
                    {/* invite path '/i/' + faux URL bars (evokes /i/{token}), light */}
                    <text x="99" y="89.5" fill="#f4f4f5" fontSize="9" fontWeight="700" fontFamily="ui-monospace, SFMono-Regular, Menlo, monospace" opacity="0.95">/i/</text>
                    <g fill="#e4e4e7">
                        <rect x="122" y="82.5" width="24" height="3" rx="1.5" opacity="0.9" />
                        <rect x="122" y="89" width="40" height="3" rx="1.5" opacity="0.5" />
                    </g>
                </g>
                {/* Copy button — white, echoes the real "Copy link" CTA */}
                <g filter="url(#cv-pill)">
                    <rect x="192" y="72" width="56" height="28" rx="9" fill="#ffffff" />
                    {/* copy glyph, dark on white */}
                    <g transform="translate(201, 82)" stroke="#0b0b0f" strokeWidth="1.2" fill="none" strokeLinejoin="round">
                        <rect x="2" y="-0.4" width="5" height="5" rx="1" fill="#ffffff" />
                        <rect x="0" y="1.6" width="5" height="5" rx="1" fill="#ffffff" />
                    </g>
                    <text x="213" y="89.5" fill="#0b0b0f" fontSize="8.5" fontWeight="700" fontFamily="system-ui">Copy</text>
                </g>

                {/* ===== collaborator cursors converging (glyph + chips reuse InviteCard verbatim) ===== */}
                {/* top-left — You (#a5b4fc) */}
                <g transform="translate(52, 40)" filter="url(#cv-cursor)">
                    <g transform="translate(-3, -2) scale(0.82)">
                        <path d="M5.5 3.21V20.8c0 .45.54.67.85.35l4.86-4.86a.5.5 0 0 1 .35-.15h6.87c.48 0 .72-.58.38-.92L6.35 2.85a.5.5 0 0 0-.85.36Z" fill="#a5b4fc" stroke="#fff" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
                    </g>
                    <g transform="translate(8, 16)">
                        <rect width="27" height="13" rx="3.5" fill="#a5b4fc" />
                        <text x="13.5" y="9.4" textAnchor="middle" fill="#0b0b0f" fontSize="8" fontWeight="700" fontFamily="system-ui">You</text>
                    </g>
                </g>

                {/* top-right — Maya (#6ee7b7) */}
                <g transform="translate(268, 46)" filter="url(#cv-cursor)">
                    <g transform="translate(-3, -2) scale(0.82)">
                        <path d="M5.5 3.21V20.8c0 .45.54.67.85.35l4.86-4.86a.5.5 0 0 1 .35-.15h6.87c.48 0 .72-.58.38-.92L6.35 2.85a.5.5 0 0 0-.85.36Z" fill="#6ee7b7" stroke="#fff" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
                    </g>
                    <g transform="translate(8, 16)">
                        <rect width="32" height="13" rx="3.5" fill="#6ee7b7" />
                        <text x="16" y="9.4" textAnchor="middle" fill="#0b0b0f" fontSize="8" fontWeight="700" fontFamily="system-ui">Maya</text>
                    </g>
                </g>

                {/* bottom — Sam (#7dd3fc); kept above the bottom fade band */}
                <g transform="translate(152, 120)" filter="url(#cv-cursor)">
                    <g transform="translate(-3, -2) scale(0.82)">
                        <path d="M5.5 3.21V20.8c0 .45.54.67.85.35l4.86-4.86a.5.5 0 0 1 .35-.15h6.87c.48 0 .72-.58.38-.92L6.35 2.85a.5.5 0 0 0-.85.36Z" fill="#7dd3fc" stroke="#fff" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
                    </g>
                    <g transform="translate(8, 16)">
                        <rect width="28" height="13" rx="3.5" fill="#7dd3fc" />
                        <text x="14" y="9.4" textAnchor="middle" fill="#0b0b0f" fontSize="8" fontWeight="700" fontFamily="system-ui">Sam</text>
                    </g>
                </g>

                {/* gentle bottom fade to seat the composition in the rounded-top media tile */}
                <rect x="0" y="156" width="320" height="24" fill="#0c0c10" opacity="0.55" />
            </svg>
        </div>
    );
}
