// Custom detailed SVG icons for interface nodes where a single lucide glyph
// wasn't expressive enough: a spreadsheet-style Table (filled header + cell grid)
// and a photo/film/audio Multimedia mark. They mimic lucide's API — paint with
// `currentColor` and accept className/style — so BrandIcon colours and sizes
// them exactly like every other node icon (Table uses a 24×24 box, Multimedia a
// 200×200 box for the finer detail).

import { forwardRef, type SVGProps } from 'react';

/** Spreadsheet-style data table: a filled title header over a 4×3 cell grid. */
export const TableGridIcon = forwardRef<SVGSVGElement, SVGProps<SVGSVGElement>>(
    (props, ref) => (
        <svg
            ref={ref}
            viewBox="0 0 24 24"
            width="24"
            height="24"
            fill="none"
            stroke="currentColor"
            strokeWidth={1.7}
            strokeLinecap="round"
            strokeLinejoin="round"
            {...props}
        >
            {/* outer frame */}
            <rect x="3" y="3.5" width="18" height="17" rx="2.5" />
            {/* header divider + title bar */}
            <path d="M3 8.6h18" />
            <rect x="5.6" y="5.35" width="8.8" height="1.7" rx="0.85" fill="currentColor" stroke="none" />
            {/* column dividers */}
            <path d="M7.5 8.6v11.9M12 8.6v11.9M16.5 8.6v11.9" />
            {/* row dividers */}
            <path d="M3 12.9h18M3 17.2h18" />
        </svg>
    ),
);
TableGridIcon.displayName = 'TableGridIcon';

/** Multimedia — a faithful vector trace of the reference stock icon (a
 *  filmstrip + a photo frame + a circle with a beamed music note). A single
 *  evenodd path (the trace already carries every white knockout gap as
 *  unfilled space), painted with currentColor so BrandIcon colours/sizes it. */
export const MultimediaIcon = forwardRef<SVGSVGElement, SVGProps<SVGSVGElement>>(
    (props, ref) => (
        <svg ref={ref} viewBox="2.50 31.00 198.00 146.75" width="24" height="24" fill="currentColor" {...props}>
            <path fillRule="evenodd" clipRule="evenodd" d="M144.50 80.00L135.00 82.00L125.75 86.25L118.75 91.25L111.75 98.75L107.00 106.50L104.00 114.50L102.50 125.00L103.00 134.50L106.00 145.00L109.25 151.25L114.25 158.00L120.00 163.50L128.00 168.75L135.25 171.75L145.50 173.75L154.00 173.75L163.50 171.75L172.75 167.75L181.00 161.75L185.75 156.75L191.50 148.00L194.75 140.00L196.50 128.75L195.75 118.00L193.75 110.75L190.50 103.75L184.75 95.75L177.50 89.00L171.50 85.25L164.00 82.00L154.25 80.00ZM173.50 97.00L174.00 97.50L174.00 142.50L172.75 145.00L171.00 146.75L166.25 149.00L161.00 149.00L157.50 147.75L155.25 146.00L153.00 142.25L153.00 139.50L153.75 137.50L157.50 133.75L161.75 132.50L167.25 133.00L168.25 132.25L168.25 110.50L166.00 110.00L138.50 113.50L138.25 146.50L137.75 148.25L134.50 151.75L129.50 153.50L123.50 153.00L118.75 149.50L117.25 146.25L117.25 144.00L118.25 141.50L120.50 139.00L126.00 136.75L132.50 137.25L132.75 102.00L139.50 100.75ZM7.25 65.50L6.50 66.50L6.75 153.00L7.50 153.50L93.50 153.50L94.00 153.00L94.00 104.00L77.25 103.75L76.50 106.00L75.25 106.75L24.75 106.50L24.00 105.50L24.25 71.75L25.00 71.25L47.50 71.25L47.75 66.00L47.25 65.50ZM79.75 143.50L81.50 141.75L89.50 141.75L91.00 143.00L91.50 145.25L89.00 147.75L82.25 147.75L80.00 146.25ZM9.25 144.00L11.25 141.75L19.25 141.75L21.00 143.50L21.00 145.75L18.50 147.75L11.75 147.75L9.75 146.25ZM79.75 131.75L82.50 129.75L88.50 129.75L91.00 131.25L91.50 133.25L91.00 134.50L89.25 136.00L82.00 136.00L80.00 134.50ZM9.25 132.50L9.75 131.25L12.00 129.75L18.25 129.75L21.00 131.75L21.00 134.00L18.50 136.00L11.50 136.00L9.75 134.50ZM79.75 120.25L82.00 118.25L89.25 118.25L91.00 119.50L91.50 121.75L89.75 124.00L82.50 124.25L80.00 122.75ZM21.00 120.25L20.75 122.75L18.25 124.25L11.00 124.00L9.25 121.75L9.75 119.50L11.50 118.25L19.00 118.25ZM24.00 113.25L25.25 112.25L76.00 112.50L76.75 113.50L76.50 147.25L75.75 147.75L24.50 147.50L24.00 146.50ZM79.75 108.50L82.00 106.50L89.00 106.50L90.75 107.50L91.50 110.00L90.50 111.75L88.75 112.50L82.25 112.50L80.00 111.00ZM9.25 108.75L10.50 107.00L11.75 106.50L18.75 106.50L20.75 108.00L21.00 110.50L18.50 112.50L12.00 112.50L10.00 111.50ZM9.25 97.25L11.50 94.75L19.00 94.75L21.00 96.50L21.00 98.75L18.75 100.75L11.50 100.75L9.75 99.50ZM9.25 85.50L9.75 84.25L11.50 83.00L19.00 83.00L21.00 85.00L21.00 87.25L19.00 89.00L11.50 89.00L9.50 87.25ZM9.25 73.75L9.75 72.50L11.75 71.25L18.50 71.25L20.75 72.75L21.00 75.25L19.50 77.00L11.75 77.25L10.00 76.25ZM124.75 81.00L111.50 59.00L110.25 58.75L99.25 75.25L95.50 74.00L88.25 70.00L87.00 70.00L70.75 86.25L70.75 87.00L116.50 87.00L124.50 81.75ZM75.25 48.00L73.50 49.00L71.00 51.75L70.00 54.00L70.00 58.50L71.75 61.75L74.00 63.75L76.25 64.75L81.00 64.75L84.50 62.75L86.75 59.50L87.25 57.50L86.75 52.75L84.50 49.75L81.75 48.00L79.50 47.50ZM52.25 35.50L52.50 99.50L105.50 99.50L109.50 94.50L109.25 94.00L58.75 94.00L58.00 93.50L57.75 41.50L58.50 40.75L139.50 40.75L140.25 41.50L140.25 75.50L143.00 75.75L145.75 75.00L146.00 36.50L145.25 35.00L53.25 35.00Z" />
        </svg>
    ),
);
MultimediaIcon.displayName = 'MultimediaIcon';
