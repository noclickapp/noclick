/**
 * Custom remark plugin to transform @[youtube](VIDEO_ID) syntax into YouTube iframe embeds.
 * Supports both standard syntax and timestamps: @[youtube](VIDEO_ID?t=123)
 */
import { visit } from 'unist-util-visit';
import type { Plugin } from 'unified';
import type { Root, Paragraph, HTML, Text, Link } from 'mdast';

const remarkYoutube: Plugin<[], Root> = () => {
  return (tree) => {
    visit(tree, 'paragraph', (node: Paragraph, index, parent) => {
      // Check for pattern: "@" text node followed by link node with text "youtube"
      // OR just a single link with text matching youtube patterns

      let videoId: string | null = null;
      let isYoutubeEmbed = false;

      // Pattern 1: @[youtube](VIDEO_ID) - creates text "@" + link "youtube"
      if (node.children.length === 2) {
        const firstChild = node.children[0] as Text;
        const secondChild = node.children[1] as Link;

        if (
          firstChild.type === 'text' &&
          firstChild.value === '@' &&
          secondChild.type === 'link'
        ) {
          const linkText = (secondChild.children[0] as Text)?.value || '';
          if (linkText.toLowerCase() === 'youtube') {
            videoId = secondChild.url;
            isYoutubeEmbed = true;
          }
        }
      }

      // Pattern 2: Single link with text like "@youtube" or "youtube"
      if (node.children.length === 1 && node.children[0].type === 'link') {
        const linkNode = node.children[0] as Link;
        const linkText = (linkNode.children[0] as Text)?.value || '';

        if (linkText.match(/^@?youtube$/i)) {
          videoId = linkNode.url;
          isYoutubeEmbed = true;
        }
      }

      if (!isYoutubeEmbed || !videoId) {
        return;
      }

      // Extract video ID from various URL formats
      let cleanVideoId = videoId;
      if (videoId.startsWith('youtube:')) {
        cleanVideoId = videoId.replace('youtube:', '');
      } else if (videoId.includes('youtube.com') || videoId.includes('youtu.be')) {
        const match = videoId.match(/(?:youtube\.com\/watch\?v=|youtu\.be\/)([^&?]+)/);
        cleanVideoId = match ? match[1] : videoId;
      }

      // Security: Validate video ID and extract query parameters
      const [baseVideoId, ...queryParts] = cleanVideoId.split('?');
      const queryString = queryParts.join('?');

      // Validate video ID format (YouTube IDs: 11 chars, alphanumeric + hyphens/underscores)
      if (!/^[a-zA-Z0-9_-]{11}$/.test(baseVideoId)) {
        console.warn('[remark-youtube] Invalid video ID format:', baseVideoId);
        return; // Skip this embed
      }

      // Validate query parameters (only allow safe URL parameter characters)
      if (queryString && !/^[a-zA-Z0-9_=&-]+$/.test(queryString)) {
        console.warn('[remark-youtube] Invalid query parameters:', queryString);
        return; // Skip this embed
      }

      // Construct safe embed URL
      const safeEmbedUrl = queryString
        ? `https://www.youtube.com/embed/${baseVideoId}?${queryString}`
        : `https://www.youtube.com/embed/${baseVideoId}`;

      // Create responsive YouTube embed HTML
      const embedHtml = `
<div class="youtube-embed-wrapper" style="position: relative; padding-bottom: 56.25%; height: 0; overflow: hidden; max-width: 100%; margin: 0 0 1rem 0; border-radius: 0.5rem;">
  <iframe
    style="position: absolute; top: 0; left: 0; width: 100%; height: 100%; border: 0; border-radius: 0.5rem;"
    src="${safeEmbedUrl}"
    frameborder="0"
    allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
    allowfullscreen
  ></iframe>
</div>`.trim();

      // Replace paragraph node with HTML node
      const htmlNode: HTML = {
        type: 'html',
        value: embedHtml,
      };

      if (parent && typeof index === 'number') {
        parent.children[index] = htmlNode;
      }
    });
  };
};

export default remarkYoutube;
