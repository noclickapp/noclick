import type { Config } from 'tailwindcss';

export default {
    darkMode: ['class'],
    content: [
        './app/**/{**,.client,.server}/**/*.{js,jsx,ts,tsx}',
        './app/**/*.{md,mdx}',
    ],
    theme: {
        extend: {
            fontFamily: {
                sans: [
                    'Inter Variable',
                    'Inter',
                    'ui-sans-serif',
                    'system-ui',
                    'sans-serif',
                    'Apple Color Emoji',
                    'Segoe UI Emoji',
                    'Segoe UI Symbol',
                    'Noto Color Emoji',
                ],
                brand: [
                    'Outfit Variable',
                    'Outfit',
                    'ui-sans-serif',
                    'system-ui',
                    'sans-serif',
                ],
            },
            borderRadius: {
                lg: 'var(--radius)',
                md: 'calc(var(--radius) - 2px)',
                sm: 'calc(var(--radius) - 4px)',
            },
            colors: {
                background: 'hsl(var(--background))',
                foreground: 'hsl(var(--foreground))',
                card: {
                    DEFAULT: 'hsl(var(--card))',
                    foreground: 'hsl(var(--card-foreground))',
                },
                sunken: 'hsl(var(--sunken))',
                popover: {
                    DEFAULT: 'hsl(var(--popover))',
                    foreground: 'hsl(var(--popover-foreground))',
                },
                primary: {
                    DEFAULT: 'hsl(var(--primary))',
                    foreground: 'hsl(var(--primary-foreground))',
                },
                secondary: {
                    DEFAULT: 'hsl(var(--secondary))',
                    foreground: 'hsl(var(--secondary-foreground))',
                },
                muted: {
                    DEFAULT: 'hsl(var(--muted))',
                    foreground: 'hsl(var(--muted-foreground))',
                },
                accent: {
                    DEFAULT: 'hsl(var(--accent))',
                    foreground: 'hsl(var(--accent-foreground))',
                },
                destructive: {
                    DEFAULT: 'hsl(var(--destructive))',
                    foreground: 'hsl(var(--destructive-foreground))',
                },
                border: 'hsl(var(--border))',
                input: 'hsl(var(--input))',
                ring: 'hsl(var(--ring))',
                chart: {
                    '1': 'hsl(var(--chart-1))',
                    '2': 'hsl(var(--chart-2))',
                    '3': 'hsl(var(--chart-3))',
                    '4': 'hsl(var(--chart-4))',
                    '5': 'hsl(var(--chart-5))',
                },
            },
            keyframes: {
                shimmer: {
                    '0%': { transform: 'translateX(-100%)' },
                    '100%': { transform: 'translateX(100%)' },
                },
                'slide-up': {
                    '0%': {
                        transform: 'translateY(100%)'
                    },
                    '100%': {
                        transform: 'translateY(0)'
                    },
                },
                'ribbon-fade-in': {
                    '0%': { opacity: '0', filter: 'blur(8px)', transform: 'translateY(4px)' },
                    '100%': { opacity: '1', filter: 'blur(0)', transform: 'translateY(0)' },
                },
                // Opacity-only fade for the hero suggestion-pill row on tab switch.
                // Replaces a framer-motion AnimatePresence (removed to keep framer
                // out of the eager landing bundle); no blur, so it stays compositor-cheap.
                'pill-fade-in': {
                    '0%': { opacity: '0' },
                    '100%': { opacity: '1' },
                },
            },
            animation: {
                shimmer: 'shimmer 2.5s ease-in-out infinite',
                'slide-up': 'slide-up 0.3s cubic-bezier(0.16, 1, 0.3, 1)',
                'ribbon-fade-in': 'ribbon-fade-in 575ms cubic-bezier(0.22, 1, 0.36, 1)',
                'pill-fade-in': 'pill-fade-in 200ms ease-out',
            },
        },
    },
    plugins: [
        require('tailwindcss-animate'),
        require('@tailwindcss/typography'),
        require('@tailwindcss/container-queries'),
    ],
} satisfies Config;
