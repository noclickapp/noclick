/**
 * SEO meta tag helpers — generates a consistent set of OpenGraph + Twitter card
 * descriptors for Remix `meta` exports. Centralized here so every public route
 * emits the same shape (title, description, og:image, twitter:card, canonical).
 */

// Canonical URLs use the public www origin consistently across metadata.
export const SITE_URL = 'https://www.noclick.com';
export const SITE_NAME = 'NoClick';
export const DEFAULT_OG_IMAGE = `${SITE_URL}/og-image.png`;
export const DEFAULT_TITLE = 'NoClick | Build Apps & Agents with AI';
export const DEFAULT_DESCRIPTION =
    'Build the agentic layer for your business. Scalable AI agents and automations that grow with your organization.';

type SeoMetaInput = {
    title: string;
    description: string;
    /** Path or absolute URL. If omitted, no canonical/og:url is emitted. */
    url?: string;
    /** Path or absolute URL. Defaults to the site-wide OG image. */
    image?: string;
    /** og:type — defaults to "website". Use "article" for blog posts. */
    type?: 'website' | 'article' | 'profile';
    /** When true, adds robots meta with index, follow. */
    indexable?: boolean;
    /**
     * schema.org JSON-LD payload(s), serialized into `<script type="application/ld+json">`
     * tags via Remix's `script:ld+json` meta descriptor. Pass an array to emit multiple
     * top-level schemas (e.g. SoftwareApplication + FAQPage on the same page).
     */
    jsonLd?: Record<string, unknown> | Record<string, unknown>[];
    /** Extra keywords for the meta keywords tag. */
    keywords?: string;
};

const toAbsolute = (value: string | undefined, fallback: string): string => {
    if (!value) return fallback;
    if (value.startsWith('http://') || value.startsWith('https://')) return value;
    return `${SITE_URL}${value.startsWith('/') ? value : `/${value}`}`;
};

/**
 * Build the standard SEO meta descriptor list for a Remix route.
 * Returns an array suitable for spreading into a `meta` function's return value.
 */
export function buildSeoMeta(input: SeoMetaInput) {
    const {
        title,
        description,
        url,
        image,
        type = 'website',
        indexable = true,
        jsonLd,
        keywords,
    } = input;

    const ogImage = toAbsolute(image, DEFAULT_OG_IMAGE);
    const canonical = url ? toAbsolute(url, SITE_URL) : undefined;

    const tags: Array<Record<string, unknown>> = [
        { title },
        { name: 'description', content: description },
        // Open Graph
        { property: 'og:title', content: title },
        { property: 'og:description', content: description },
        { property: 'og:type', content: type },
        { property: 'og:site_name', content: SITE_NAME },
        { property: 'og:image', content: ogImage },
        { property: 'og:image:width', content: '1200' },
        { property: 'og:image:height', content: '630' },
        // Twitter
        { name: 'twitter:card', content: 'summary_large_image' },
        { name: 'twitter:title', content: title },
        { name: 'twitter:description', content: description },
        { name: 'twitter:image', content: ogImage },
        { name: 'twitter:site', content: '@noclickapp' },
    ];

    if (canonical) {
        tags.push({ property: 'og:url', content: canonical });
        tags.push({ tagName: 'link', rel: 'canonical', href: canonical });
    }

    if (indexable) {
        tags.push({ name: 'robots', content: 'index, follow' });
    } else {
        tags.push({ name: 'robots', content: 'noindex, nofollow' });
    }

    if (keywords) {
        tags.push({ name: 'keywords', content: keywords });
    }


    if (jsonLd) {
        const payloads = Array.isArray(jsonLd) ? jsonLd : [jsonLd];
        for (const payload of payloads) {
            tags.push({ 'script:ld+json': payload });
        }
    }

    return tags;
}

type BlogPostingInput = {
    title: string;
    description: string;
    /** Path or absolute URL — used for both schema `url` and `mainEntityOfPage`. */
    url: string;
    /** Path or absolute URL of the post's hero image. */
    image: string;
    /** ISO date string (yyyy-mm-dd is fine). */
    datePublished: string;
    /** ISO date string. Defaults to `datePublished`. */
    dateModified?: string;
    authorName?: string;
    keywords?: string;
};

/**
 * Build a `BreadcrumbList` JSON-LD payload. Pass the trail from root to current
 * page. `url` accepts a path or absolute URL; the last item's url may be omitted.
 */
export function buildBreadcrumbJsonLd(
    items: Array<{ name: string; url?: string }>
): Record<string, unknown> {
    return {
        '@context': 'https://schema.org',
        '@type': 'BreadcrumbList',
        itemListElement: items.map((item, index) => ({
            '@type': 'ListItem',
            position: index + 1,
            name: item.name,
            ...(item.url ? { item: toAbsolute(item.url, SITE_URL) } : {}),
        })),
    };
}

/** Build an `FAQPage` JSON-LD payload from a list of question/answer pairs. */
export function buildFaqJsonLd(
    faqs: Array<{ question: string; answer: string }>
): Record<string, unknown> {
    return {
        '@context': 'https://schema.org',
        '@type': 'FAQPage',
        mainEntity: faqs.map((faq) => ({
            '@type': 'Question',
            name: faq.question,
            acceptedAnswer: {
                '@type': 'Answer',
                text: faq.answer,
            },
        })),
    };
}

/** Build a `HowTo` JSON-LD payload from an ordered list of setup steps. */
export function buildHowToJsonLd(input: {
    name: string;
    description?: string;
    steps: Array<{ name: string; text: string }>;
}): Record<string, unknown> {
    return {
        '@context': 'https://schema.org',
        '@type': 'HowTo',
        name: input.name,
        ...(input.description ? { description: input.description } : {}),
        step: input.steps.map((s, i) => ({
            '@type': 'HowToStep',
            position: i + 1,
            name: s.name,
            text: s.text,
        })),
    };
}

/** Build a `BlogPosting` JSON-LD payload for an article-style page. */
export function buildBlogPostingJsonLd(input: BlogPostingInput): Record<string, unknown> {
    const url = toAbsolute(input.url, SITE_URL);
    const image = toAbsolute(input.image, DEFAULT_OG_IMAGE);
    return {
        '@context': 'https://schema.org',
        '@type': 'BlogPosting',
        headline: input.title,
        description: input.description,
        image,
        url,
        mainEntityOfPage: {
            '@type': 'WebPage',
            '@id': url,
        },
        datePublished: input.datePublished,
        dateModified: input.dateModified ?? input.datePublished,
        author: {
            '@type': 'Organization',
            name: input.authorName ?? SITE_NAME,
            url: SITE_URL,
        },
        publisher: {
            '@type': 'Organization',
            name: SITE_NAME,
            url: SITE_URL,
            logo: {
                '@type': 'ImageObject',
                url: `${SITE_URL}/logos/logo-dark-512.png`,
            },
        },
        ...(input.keywords ? { keywords: input.keywords } : {}),
    };
}
