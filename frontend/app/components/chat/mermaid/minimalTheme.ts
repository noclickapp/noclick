/**
 * Mermaid diagram theme configuration for dark mode and sticky notes.
 * Provides a minimal dark theme for chat messages and customizable theme generation for sticky notes
 * with light/transparent backgrounds. Uses YAML frontmatter injection for per-diagram theming.
 */

// Base dark theme configuration for Mermaid diagrams in chat messages
export const CORRECT_MERMAID_CONFIG = {
  startOnLoad: false,
  securityLevel: 'loose' as const,
  theme: 'base' as const, // MUST use base - it's the only customizable theme
  themeVariables: {
    // Enable dark mode calculations
    darkMode: true,

    // DON'T set primaryColor - it affects pie charts!
    // Instead, set specific diagram colors

    // Background and general text
    background: '#1a1a1a',
    fontFamily: 'ui-sans-serif, system-ui, sans-serif',
    fontSize: '14px',

    // Text colors
    primaryTextColor: '#e2e8f0',
    textColor: '#e2e8f0',

    // Lines and edges
    lineColor: '#666666',
    primaryBorderColor: '#666666',

    // Main background for nodes (NOT pie slices)
    mainBkg: '#2E2E2E',

    // Flowchart specific (these WORK)
    nodeBkg: '#2E2E2E',
    nodeBorder: '#666666',
    nodeTextColor: '#e2e8f0',
    clusterBkg: '#2E2E2E',
    clusterBorder: '#666666',
    defaultLinkColor: '#666666',
    edgeLabelBackground: '#2E2E2E',

    // Sequence diagram (these WORK)
    actorBkg: '#2E2E2E',
    actorBorder: '#666666',
    actorTextColor: '#e2e8f0',
    signalColor: '#e2e8f0',
    signalTextColor: '#e2e8f0',

    // Pie chart - diverse colors optimized for dark theme
    pie1: '#60A5FA',  // Sky blue
    pie2: '#34D399',  // Emerald
    pie3: '#A78BFA',  // Purple
    pie4: '#FB923C',  // Orange
    pie5: '#F87171',  // Red
    pie6: '#FBBF24',  // Amber
    pie7: '#A3E635',  // Lime
    pie8: '#2DD4BF',  // Teal
    pie9: '#E879F9',  // Fuchsia
    pie10: '#38BDF8', // Light blue
    pie11: '#C084FC', // Violet
    pie12: '#FACC15', // Yellow
    pieTitleTextColor: '#e2e8f0',
    pieSectionTextColor: '#e2e8f0',
    pieLegendTextColor: '#e2e8f0',
    pieStrokeColor: '#666666',
    pieOuterStrokeColor: '#666666',

    // State diagram
    stateBkg: '#2E2E2E',
    stateLabelColor: '#e2e8f0',
    altBackground: '#2E2E2E',

    // Class diagram
    classText: '#e2e8f0',
  }
};

// Minimal CSS for ONLY what's broken (mindmaps)
export const MINDMAP_FIX_CSS = `
  /* Mindmap fix - NOT in official docs, doesn't respect theme */
  .mindmap circle,
  .mindmap rect,
  .mindmap ellipse,
  .mindmap path:not([id*="arrow"]) {
    fill: #2E2E2E !important;
    stroke: #666666 !important;
  }

  .mindmap text {
    fill: #e2e8f0 !important;
  }
`;

/**
 * Create a custom Mermaid theme configuration for sticky notes
 * Merges sticky note colors with the base dark theme configuration
 */
export function createStickyNoteThemeConfig(colors: {
  nodeFill: string;
  nodeStroke: string;
  textFill: string;
  edgeLabelBg: string;
}) {
  return {
    ...CORRECT_MERMAID_CONFIG,
    themeVariables: {
      ...CORRECT_MERMAID_CONFIG.themeVariables,

      // Disable dark mode for sticky notes to prevent dark color calculations
      darkMode: false,

      // Override the SVG background to be transparent (not dark)
      background: 'transparent',

      // Override node backgrounds and borders
      mainBkg: colors.nodeFill,
      nodeBkg: colors.nodeFill,
      nodeBorder: colors.nodeStroke,

      // Override all text colors
      nodeTextColor: colors.textFill,
      primaryTextColor: colors.textFill,
      textColor: colors.textFill,

      // Override edge/line colors
      lineColor: colors.nodeStroke,
      primaryBorderColor: colors.nodeStroke,
      defaultLinkColor: colors.nodeStroke,
      edgeLabelBackground: colors.edgeLabelBg,

      // Flowchart specific
      clusterBkg: colors.nodeFill,
      clusterBorder: colors.nodeStroke,

      // Sequence diagram
      actorBkg: colors.nodeFill,
      actorBorder: colors.nodeStroke,
      actorTextColor: colors.textFill,
      signalColor: colors.textFill,
      signalTextColor: colors.textFill,

      // State diagram
      stateBkg: colors.nodeFill,
      stateLabelColor: colors.textFill,
      altBackground: colors.nodeFill,

      // Class diagram
      classText: colors.textFill,
    }
  };
}

// Simple detection
export function needsOverride(definition: string): boolean {
  return definition.trim().toLowerCase().startsWith('mindmap');
}

// Check if diagram is a pie chart
export function isPieChart(definition: string): boolean {
  return definition.trim().toLowerCase().startsWith('pie');
}

// The absolute minimum fix for mindmaps
export function fixMindmap(container: HTMLElement): void {
  // Check if this is actually a mindmap (not a pie chart)
  const svg = container.querySelector('svg');
  if (svg?.getAttribute('aria-roledescription') === 'pie') {
    // Don't touch pie charts!
    return;
  }

  // Mindmaps generate circles and rects with inline styles
  // We need to override ALL circles and rects in the mindmap

  // Fix all circles (mindmap nodes are often circles)
  container.querySelectorAll('circle').forEach(el => {
    const circle = el as SVGCircleElement;
    // Check if it has a fill that looks like a light color
    const currentFill = circle.getAttribute('fill') || circle.style.fill;
    if (currentFill && (currentFill.includes('rgb') || currentFill.includes('#'))) {
      circle.style.fill = '#2E2E2E';
      circle.style.stroke = '#666666';
    }
  });

  // Fix all rects (some mindmap nodes are rectangles)
  container.querySelectorAll('rect').forEach(el => {
    const rect = el as SVGRectElement;
    const currentFill = rect.getAttribute('fill') || rect.style.fill;
    if (currentFill && (currentFill.includes('rgb') || currentFill.includes('#'))) {
      rect.style.fill = '#2E2E2E';
      rect.style.stroke = '#666666';
    }
  });

  // Fix all ellipses if any
  container.querySelectorAll('ellipse').forEach(el => {
    const ellipse = el as SVGEllipseElement;
    const currentFill = ellipse.getAttribute('fill') || ellipse.style.fill;
    if (currentFill && (currentFill.includes('rgb') || currentFill.includes('#'))) {
      ellipse.style.fill = '#2E2E2E';
      ellipse.style.stroke = '#666666';
    }
  });

  // Fix text colors - target all text in the SVG
  container.querySelectorAll('text').forEach(el => {
    (el as SVGElement).style.fill = '#e2e8f0';
  });

  // Fix paths that might be node backgrounds
  container.querySelectorAll('path').forEach(el => {
    const path = el as SVGPathElement;
    // Skip arrows and lines
    if (!path.id?.includes('arrow') && !path.classList.contains('link')) {
      const currentFill = path.getAttribute('fill') || path.style.fill;
      // Only change if it has a fill (not just stroke)
      if (currentFill && currentFill !== 'none') {
        path.style.fill = '#2E2E2E';
        path.style.stroke = '#666666';
      }
    }
  });
}