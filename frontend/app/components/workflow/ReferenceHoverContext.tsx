// ReferenceHoverContext provides shared state for highlighting JSON fields when hovering
// over references in configuration fields. When a user hovers over {{nodeId.path}},
// the corresponding field in the Input panel gets highlighted.
// Also handles click-to-scroll functionality for navigating to referenced fields.
// Includes auto-expand functionality for nested paths.

import { createContext, useContext, useState, useCallback, ReactNode } from 'react';

interface ReferenceLocation {
    nodeId: string;
    path: string;
}

interface ReferenceHoverContextValue {
    hoveredReference: ReferenceLocation | null;
    setHoveredReference: (ref: ReferenceLocation | null) => void;
    // Reference that was clicked - triggers scroll-to behavior in Input panel
    scrollToReference: ReferenceLocation | null;
    setScrollToReference: (ref: ReferenceLocation | null) => void;
    // Paths that should be expanded to reveal nested fields
    pathsToExpand: Set<string>;
}

// Helper to extract all parent paths from a full path
// e.g., "output.data.nested.field" -> ["output", "output.data", "output.data.nested", "output.data.nested.field"]
export const getParentPaths = (nodeId: string, path: string): string[] => {
    const paths: string[] = [];
    const parts = path.split(/\.|\[/).map(p => p.replaceAll(']', ''));
    let current = '';

    for (let i = 0; i < parts.length; i++) {
        if (i === 0) {
            current = parts[i];
        } else if (path.includes(`[${parts[i]}]`) || path.includes(`[${parts[i]}`)) {
            current = `${current}[${parts[i]}]`;
        } else {
            current = `${current}.${parts[i]}`;
        }
        paths.push(`${nodeId}:${current}`);
    }

    return paths;
};

const ReferenceHoverContext = createContext<ReferenceHoverContextValue | null>(null);

export const ReferenceHoverProvider = ({ children }: { children: ReactNode }) => {
    const [hoveredReference, setHoveredReference] = useState<ReferenceLocation | null>(null);
    const [scrollToReference, setScrollToReference] = useState<ReferenceLocation | null>(null);
    const [pathsToExpand, setPathsToExpand] = useState<Set<string>>(new Set());

    const handleSetHoveredReference = useCallback((ref: ReferenceLocation | null) => {
        setHoveredReference(ref);
    }, []);

    const handleSetScrollToReference = useCallback((ref: ReferenceLocation | null) => {
        setScrollToReference(ref);

        if (ref) {
            // Calculate all parent paths that need to be expanded
            const parentPaths = getParentPaths(ref.nodeId, ref.path);
            setPathsToExpand(new Set(parentPaths));

            // Auto-clear after a short delay to allow scroll/expand to complete
            setTimeout(() => {
                setScrollToReference(null);
                setPathsToExpand(new Set());
            }, 800);
        }
    }, []);

    return (
        <ReferenceHoverContext.Provider value={{
            hoveredReference,
            setHoveredReference: handleSetHoveredReference,
            scrollToReference,
            setScrollToReference: handleSetScrollToReference,
            pathsToExpand,
        }}>
            {children}
        </ReferenceHoverContext.Provider>
    );
};

export const useReferenceHover = () => {
    const context = useContext(ReferenceHoverContext);
    // Return null if not wrapped in provider - allows graceful degradation
    return context;
};

// Helper to check if a path matches a reference (hovered or scrollTo)
// Handles both exact matches and prefix matches for nested paths
export const isPathHighlighted = (
    reference: ReferenceLocation | null,
    nodeId: string,
    path: string
): boolean => {
    if (!reference) return false;
    if (reference.nodeId !== nodeId) return false;

    // Exact match
    if (reference.path === path) return true;

    // Check if reference path is a parent of current path (e.g., "output" matches "output.field")
    if (path.startsWith(reference.path + '.') || path.startsWith(reference.path + '[')) {
        return true;
    }

    // Check if current path is a parent of reference path (e.g., "output.data" should highlight when hovering "output.data.field")
    if (reference.path.startsWith(path + '.') || reference.path.startsWith(path + '[')) {
        return true;
    }

    return false;
};

// Helper to check if this exact path should be scrolled to (exact match only)
export const shouldScrollToPath = (
    scrollToReference: ReferenceLocation | null,
    nodeId: string,
    path: string
): boolean => {
    if (!scrollToReference) return false;
    return scrollToReference.nodeId === nodeId && scrollToReference.path === path;
};

// Helper to check if a path should be expanded (to reveal nested fields)
export const shouldExpandPath = (
    pathsToExpand: Set<string>,
    nodeId: string,
    path: string
): boolean => {
    return pathsToExpand.has(`${nodeId}:${path}`);
};
