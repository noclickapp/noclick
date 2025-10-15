// Unified Mermaid diagram rendering function
// Used by both inline and popup views for consistency

import mermaid from 'mermaid';
import { CORRECT_MERMAID_CONFIG, needsOverride, fixMindmap, createStickyNoteThemeConfig } from './minimalTheme';

/**
 * Render a Mermaid diagram with consistent dark theme
 * This function is used for both inline and popup diagrams
 *
 * @param container - The HTML element to render into
 * @param definition - The Mermaid diagram definition
 * @param isPopup - Whether this is for a popup (affects scope ID)
 * @returns Promise that resolves when rendering is complete
 */
export async function renderMermaidDiagram(
  container: HTMLElement,
  definition: string,
  _isPopup: boolean = false
): Promise<void> {
  try {
    // Generate unique ID for this diagram
    const id = `mermaid-${Date.now()}-${Math.random().toString(36).substring(2, 9)}`;

    // Check if we're in a sticky note context (has custom theme colors)
    const sourceElement = container.parentElement || container;
    const computedStyle = getComputedStyle(sourceElement);
    const customFill = computedStyle.getPropertyValue('--mermaid-node-fill').trim();

    // Prepare the diagram definition with frontmatter config if in sticky note context
    let finalDefinition = definition;
    if (customFill) {
      // Sticky note context - create light theme config
      const themeConfig = createStickyNoteThemeConfig({
        nodeFill: customFill,
        nodeStroke: computedStyle.getPropertyValue('--mermaid-node-stroke').trim(),
        textFill: computedStyle.getPropertyValue('--mermaid-text-fill').trim(),
        edgeLabelBg: computedStyle.getPropertyValue('--mermaid-edge-label-bg').trim(),
      });

      // Inject YAML frontmatter with theme configuration
      // This is the correct way to pass per-diagram config in Mermaid v11
      const frontmatter = `---
config:
  theme: ${themeConfig.theme}
  themeVariables:
${Object.entries(themeConfig.themeVariables)
  .map(([key, value]) => `    ${key}: ${typeof value === 'string' ? `'${value}'` : value}`)
  .join('\n')}
---
`;
      finalDefinition = frontmatter + definition;
    }

    // Render the diagram (with just 2 parameters - the Mermaid v11 API)
    const { svg } = await mermaid.render(id, finalDefinition);

    // Clear container and insert SVG
    container.innerHTML = svg;

    // Get diagram type for specific fixes
    const diagramType = definition.trim().split(/\s/)[0].toLowerCase();

    // Apply minimal fix for mindmaps (known Mermaid bug)
    if (needsOverride(definition)) {
      fixMindmap(container);
    }

    // Apply CSS fix for journey diagram excessive whitespace
    // See: https://github.com/mermaid-js/mermaid/issues/3501
    if (diagramType === 'journey') {
      const svgEl = container.querySelector('svg');
      if (svgEl) {
        // Apply suggested CSS fix from GitHub issue
        svgEl.style.maxWidth = '100%';
        svgEl.style.height = 'auto';
        svgEl.style.display = 'block';
        svgEl.style.margin = '0 auto';
      }
    }

    // No additional CSS injection needed - Mermaid now generates correct colors from upstream config

    // Clean up any stray error elements
    const errorElements = document.querySelectorAll('[aria-roledescription="error"]');
    errorElements.forEach(el => el.remove());
  } catch (error) {
    console.error('Mermaid rendering error:', error);

    // Display error message in container
    container.innerHTML = `
      <div class="p-4 bg-red-900/20 border border-red-500 rounded">
        <p class="text-red-400">Failed to render Mermaid diagram</p>
        <pre class="text-xs mt-2 text-red-300">${error instanceof Error ? error.message : String(error)}</pre>
      </div>
    `;

    // Clean up any error elements that Mermaid might have inserted
    const errorSvgs = document.querySelectorAll('[aria-roledescription="error"]');
    errorSvgs.forEach(el => el.remove());
  }
}

/**
 * Initialize Mermaid with dark theme configuration
 * Should be called once when the app loads
 */
// Track if we've initialized
let isInitialized = false;

export function initializeMermaid(): void {
  if (typeof window === 'undefined' || isInitialized) return;

  mermaid.initialize(CORRECT_MERMAID_CONFIG);

  isInitialized = true;
}