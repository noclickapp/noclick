// Unified Mermaid diagram rendering function
// Used by both inline and popup views for consistency

import mermaid from 'mermaid';
import { CORRECT_MERMAID_CONFIG, needsOverride, fixMindmap } from './minimalTheme';

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

    // Render the diagram
    const { svg } = await mermaid.render(id, definition);

    // Clear container and insert SVG
    container.innerHTML = svg;

    // Get diagram type for specific fixes
    const diagramType = definition.trim().split(/\s/)[0].toLowerCase();

    // Apply minimal fix for mindmaps (known Mermaid bug)
    if (needsOverride(definition)) {
      fixMindmap(container);
    }

    // Fix flowchart nodes with inline styles that have !important
    if (diagramType === 'flowchart' || diagramType === 'graph') {
      // Remove inline styles with !important that override our theme
      container.querySelectorAll('.node rect[style*="fill"]').forEach(rect => {
        const el = rect as HTMLElement;
        // Remove the inline fill style
        el.style.removeProperty('fill');
        // Apply our dark theme
        el.style.setProperty('fill', '#2E2E2E', 'important');
        el.style.setProperty('stroke', '#666666', 'important');
      });
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

    // Fix arrow markers in flowcharts (they don't respect theme)
    const svgElement = container.querySelector('svg');
    if (svgElement) {
      // Get the SVG ID for specificity (use throughout)
      const svgId = svgElement.id || id;

      // Inject minimal CSS for arrow fix and diagram-specific overrides
      const style = document.createElementNS('http://www.w3.org/2000/svg', 'style');

      let cssContent = `
        /* Fix arrow markers to be visible on dark background */
        marker path, [id*="arrowhead"] path {
          fill: #666666 !important;
          stroke: #666666 !important;
        }

        /* Default dark theme for nodes without inline styles */
        #${svgId} .node rect:not([style*="fill"]),
        #${svgId} .node circle:not([style*="fill"]),
        #${svgId} .node ellipse:not([style*="fill"]),
        #${svgId} .node polygon:not([style*="fill"]) {
          fill: #2E2E2E !important;
          stroke: #666666 !important;
        }

        /* Ensure text is always light */
        #${svgId} .nodeLabel,
        #${svgId} .label text,
        #${svgId} text {
          fill: #e2e8f0 !important;
        }
      `;

      // Add mindmap-specific overrides if needed
      if (needsOverride(definition)) {

        cssContent += `
        /* Override Mermaid's generated section styles for mindmaps */
        /* Root node needs highest specificity - target multiple ways */
        #${svgId} .section-root circle,
        #${svgId} .section-root rect,
        #${svgId} .section-root path:not(.edge),
        #${svgId} .section-root polygon,
        #${svgId} g.node circle.basic.label-container,
        #${svgId} g#node_0 circle,
        #${svgId} .mindmap-node circle.basic {
          fill: #2E2E2E !important;
          stroke: #666666 !important;
        }

        #${svgId} .section-root text,
        #${svgId} g#node_0 text {
          fill: #e2e8f0 !important;
        }

        /* Override all numbered sections */
        #${svgId} .section-0 circle, #${svgId} .section-0 rect, #${svgId} .section-0 path,
        #${svgId} .section-1 circle, #${svgId} .section-1 rect, #${svgId} .section-1 path,
        #${svgId} .section-2 circle, #${svgId} .section-2 rect, #${svgId} .section-2 path,
        #${svgId} .section-3 circle, #${svgId} .section-3 rect, #${svgId} .section-3 path,
        #${svgId} .section-4 circle, #${svgId} .section-4 rect, #${svgId} .section-4 path,
        #${svgId} .section-5 circle, #${svgId} .section-5 rect, #${svgId} .section-5 path,
        #${svgId} .section-6 circle, #${svgId} .section-6 rect, #${svgId} .section-6 path,
        #${svgId} .section-7 circle, #${svgId} .section-7 rect, #${svgId} .section-7 path,
        #${svgId} .section-8 circle, #${svgId} .section-8 rect, #${svgId} .section-8 path,
        #${svgId} .section-9 circle, #${svgId} .section-9 rect, #${svgId} .section-9 path {
          fill: #2E2E2E !important;
        }

        #${svgId} .section-0 text, #${svgId} .section-1 text, #${svgId} .section-2 text,
        #${svgId} .section-3 text, #${svgId} .section-4 text, #${svgId} .section-5 text,
        #${svgId} .section-6 text, #${svgId} .section-7 text, #${svgId} .section-8 text,
        #${svgId} .section-9 text {
          fill: #e2e8f0 !important;
        }

        /* Also target the node background paths */
        #${svgId} path.node-bkg {
          fill: #2E2E2E !important;
        }

        /* Fix edges/lines to be visible */
        #${svgId} .edge {
          stroke: #666666 !important;
          stroke-width: 2px !important;
          fill: none !important;
        }

        #${svgId} path.edge {
          stroke: #666666 !important;
          fill: none !important;
        }

        /* Ensure the root node (often class --1 or section--1) is also dark */
        #${svgId} .section--1 circle,
        #${svgId} .section--1 rect,
        #${svgId} .section--1 path:not(.edge),
        #${svgId} .section--1 polygon {
          fill: #2E2E2E !important;
          stroke: #666666 !important;
        }

        #${svgId} .section--1 text {
          fill: #e2e8f0 !important;
        }
        `;
      }

      // Add diagram-specific fixes
      const diagramType = definition.trim().split(/\s/)[0].toLowerCase();

      // Journey diagram fixes
      if (diagramType === 'journey') {
        cssContent += `
        /* Journey diagram dark theme fixes */
        #${svgId} .task,
        #${svgId} .task-type-0,
        #${svgId} .task-type-1,
        #${svgId} .task-type-2,
        #${svgId} .task-type-3,
        #${svgId} .task-type-4,
        #${svgId} .task-type-5,
        #${svgId} .task-type-6,
        #${svgId} .task-type-7 {
          fill: #2E2E2E !important;
          stroke: #666666 !important;
        }

        #${svgId} .journey-section,
        #${svgId} .section-type-0,
        #${svgId} .section-type-1,
        #${svgId} .section-type-2,
        #${svgId} .section-type-3,
        #${svgId} .section-type-4,
        #${svgId} .section-type-5,
        #${svgId} .section-type-6,
        #${svgId} .section-type-7 {
          fill: #1a1a1a !important;
          stroke: #666666 !important;
        }

        #${svgId} .label {
          color: #e2e8f0 !important;
          fill: #e2e8f0 !important;
        }

        #${svgId} .label text {
          fill: #e2e8f0 !important;
        }

        #${svgId} .legend {
          fill: #e2e8f0 !important;
        }

        #${svgId} text {
          fill: #e2e8f0 !important;
        }

        /* Fix face backgrounds */
        #${svgId} .face {
          fill: #2E2E2E !important;
          stroke: #666666 !important;
        }
        `;
      }

      // Gantt chart fixes
      if (diagramType === 'gantt') {
        cssContent += `
        /* Gantt chart dark theme fixes */
        #${svgId} .task,
        #${svgId} .task0,
        #${svgId} .task1,
        #${svgId} .task2,
        #${svgId} .task3 {
          fill: #2E2E2E !important;
          stroke: #666666 !important;
        }

        #${svgId} .active0,
        #${svgId} .active1,
        #${svgId} .active2,
        #${svgId} .active3 {
          fill: #3E3E3E !important;
          stroke: #666666 !important;
        }

        #${svgId} .section {
          fill: #1a1a1a !important;
          opacity: 0.5 !important;
        }

        #${svgId} .sectionTitle {
          fill: #e2e8f0 !important;
        }

        #${svgId} .taskText,
        #${svgId} .taskText0,
        #${svgId} .taskText1,
        #${svgId} .taskText2,
        #${svgId} .taskText3,
        #${svgId} .taskTextOutsideRight,
        #${svgId} .taskTextOutsideLeft {
          fill: #e2e8f0 !important;
        }

        #${svgId} .titleText {
          fill: #e2e8f0 !important;
        }

        #${svgId} .grid .tick text {
          fill: #e2e8f0 !important;
        }
        `;
      }

      // Git Graph fixes
      if (diagramType === 'gitgraph') {
        cssContent += `
        /* Git Graph dark theme fixes */
        #${svgId} .commit,
        #${svgId} .commit0,
        #${svgId} .commit1,
        #${svgId} .commit2,
        #${svgId} .commit3,
        #${svgId} .commit4,
        #${svgId} .commit5,
        #${svgId} .commit6,
        #${svgId} .commit7,
        #${svgId} .commit-merge {
          fill: #2E2E2E !important;
          stroke: #666666 !important;
        }

        #${svgId} .branch,
        #${svgId} .branch0,
        #${svgId} .branch1,
        #${svgId} .branch2,
        #${svgId} .branch3 {
          stroke: #666666 !important;
        }

        #${svgId} .arrow,
        #${svgId} .arrow0,
        #${svgId} .arrow1,
        #${svgId} .arrow2,
        #${svgId} .arrow3 {
          stroke: #666666 !important;
        }

        #${svgId} .branch-label,
        #${svgId} .branch-label0,
        #${svgId} .branch-label1,
        #${svgId} .branch-label2,
        #${svgId} .branch-label3,
        #${svgId} .commit-label,
        #${svgId} .tag-label {
          fill: #e2e8f0 !important;
        }

        #${svgId} .branchLabelBkg,
        #${svgId} .label0,
        #${svgId} .label1,
        #${svgId} .label2,
        #${svgId} .label3 {
          fill: #1a1a1a !important;
          stroke: #666666 !important;
        }

        #${svgId} .commit-label-bkg {
          fill: #1a1a1a !important;
          opacity: 0.8 !important;
        }
        `;
      }

      style.textContent = cssContent;
      // Append at the end to ensure our styles override Mermaid's
      svgElement.appendChild(style);
    }

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