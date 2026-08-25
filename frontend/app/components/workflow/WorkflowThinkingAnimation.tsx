/**
 * WorkflowThinkingAnimation - SVG animation displayed while AI is designing a workflow.
 * Shows a network graph that progressively builds itself with nodes appearing and
 * edges animating to simulate workflow generation. Inspired by the ScalableAgentsAnimation
 * from the landing page bento grid.
 */

import { useState, useEffect, useMemo } from 'react';
import { motion } from 'framer-motion';

interface AnimationNode {
    x: number;
    y: number;
    type: 'trigger' | 'action';
}

interface AnimationEdge {
    from: number;
    to: number;
    key: string;
}

export function WorkflowThinkingAnimation() {
    const [visibleNodes, setVisibleNodes] = useState(1);
    const [activeEdges, setActiveEdges] = useState<Set<string>>(new Set());
    const [phase, setPhase] = useState<'growing' | 'active' | 'fading'>('growing');

    // Workflow-like layout: trigger at top, branching down
    const allNodes: AnimationNode[] = useMemo(() => [
        // Trigger node (index 0) - top center
        { x: 100, y: 20, type: 'trigger' },
        // First level - processing nodes (1-2)
        { x: 60, y: 55, type: 'action' },
        { x: 140, y: 55, type: 'action' },
        // Second level - more actions (3-5)
        { x: 30, y: 90, type: 'action' },
        { x: 100, y: 90, type: 'action' },
        { x: 170, y: 90, type: 'action' },
        // Third level - endpoints (6-9)
        { x: 20, y: 125, type: 'action' },
        { x: 65, y: 125, type: 'action' },
        { x: 135, y: 125, type: 'action' },
        { x: 180, y: 125, type: 'action' },
    ], []);

    // Define edges for workflow structure (parent -> child relationships)
    const allEdges: AnimationEdge[] = useMemo(() => [
        // From trigger to first level
        { from: 0, to: 1, key: '0-1' },
        { from: 0, to: 2, key: '0-2' },
        // From first level to second level
        { from: 1, to: 3, key: '1-3' },
        { from: 1, to: 4, key: '1-4' },
        { from: 2, to: 4, key: '2-4' },
        { from: 2, to: 5, key: '2-5' },
        // From second level to third level
        { from: 3, to: 6, key: '3-6' },
        { from: 3, to: 7, key: '3-7' },
        { from: 4, to: 7, key: '4-7' },
        { from: 4, to: 8, key: '4-8' },
        { from: 5, to: 8, key: '5-8' },
        { from: 5, to: 9, key: '5-9' },
    ], []);

    // Get visible edges based on visible nodes
    const currentEdges = useMemo(() => {
        return allEdges.filter(edge => edge.from < visibleNodes && edge.to < visibleNodes);
    }, [allEdges, visibleNodes]);

    const currentNodes = allNodes.slice(0, visibleNodes);

    // Growth cycle with restart
    useEffect(() => {
        const maxNodes = allNodes.length;
        let timeout: NodeJS.Timeout;

        if (phase === 'growing') {
            if (visibleNodes < maxNodes) {
                timeout = setTimeout(() => {
                    setVisibleNodes(prev => prev + 1);
                }, 350);
            } else {
                timeout = setTimeout(() => setPhase('active'), 400);
            }
        } else if (phase === 'active') {
            timeout = setTimeout(() => setPhase('fading'), 2000);
        } else if (phase === 'fading') {
            timeout = setTimeout(() => {
                setVisibleNodes(1);
                setActiveEdges(new Set());
                setPhase('growing');
            }, 500);
        }

        return () => clearTimeout(timeout);
    }, [phase, visibleNodes, allNodes.length]);

    // Random edge activation (data flowing through workflow)
    useEffect(() => {
        if (phase !== 'fading' && currentEdges.length > 0) {
            const edgeInterval = setInterval(() => {
                const randomEdge = currentEdges[Math.floor(Math.random() * currentEdges.length)];
                setActiveEdges(prev => {
                    const next = new Set(prev);
                    next.add(randomEdge.key);
                    if (next.size > 4) {
                        const arr = Array.from(next);
                        next.delete(arr[0]);
                    }
                    return next;
                });
            }, 200);
            return () => clearInterval(edgeInterval);
        }
    }, [currentEdges, phase]);

    return (
        <div className="w-48 h-40 mx-auto mb-6">
            <svg viewBox="0 0 200 150" className="w-full h-full" preserveAspectRatio="xMidYMid meet">
                {/* Edges - curved lines for workflow feel */}
                {currentEdges.map((edge) => {
                    const from = allNodes[edge.from];
                    const to = allNodes[edge.to];
                    const midY = (from.y + to.y) / 2;
                    const path = `M ${from.x} ${from.y + 6} Q ${from.x} ${midY}, ${(from.x + to.x) / 2} ${midY} T ${to.x} ${to.y - 6}`;
                    const isActive = activeEdges.has(edge.key);

                    return (
                        <motion.path
                            key={edge.key}
                            d={path}
                            fill="none"
                            style={{ stroke: isActive ? 'hsl(var(--foreground) / 0.6)' : 'hsl(var(--foreground) / 0.15)' }}
                            strokeWidth={isActive ? 1.5 : 1}
                            initial={{ pathLength: 0, opacity: 0 }}
                            animate={{
                                pathLength: phase === 'fading' ? 0 : 1,
                                opacity: phase === 'fading' ? 0 : 1
                            }}
                            transition={{ duration: 0.3 }}
                        />
                    );
                })}

                {/* Nodes */}
                {currentNodes.map((node, i) => {
                    const isTrigger = node.type === 'trigger';
                    const nodeSize = isTrigger ? 8 : 6;
                    const outerSize = isTrigger ? 14 : 11;

                    return (
                        <motion.g key={`node-${i}`}>
                            {/* Outer ring */}
                            <motion.circle
                                cx={node.x}
                                cy={node.y}
                                r={outerSize}
                                fill="none"
                                style={{ stroke: 'hsl(var(--foreground) / 0.1)' }}
                                strokeWidth="1"
                                initial={{ scale: 0, opacity: 0 }}
                                animate={{
                                    scale: phase === 'fading' ? 0 : 1,
                                    opacity: phase === 'fading' ? 0 : 1
                                }}
                                transition={{ duration: 0.25 }}
                            />
                            {/* Inner node */}
                            <motion.circle
                                cx={node.x}
                                cy={node.y}
                                r={nodeSize}
                                style={{ fill: isTrigger ? 'hsl(var(--foreground) / 0.9)' : 'hsl(var(--foreground) / 0.7)' }}
                                initial={{ scale: 0 }}
                                animate={{ scale: phase === 'fading' ? 0 : 1 }}
                                transition={{ duration: 0.2, type: "spring", stiffness: 400, damping: 25 }}
                            />
                        </motion.g>
                    );
                })}

                {/* Pulse on newest node */}
                {phase === 'growing' && visibleNodes > 1 && (
                    <motion.circle
                        key={`pulse-${visibleNodes}`}
                        cx={currentNodes[currentNodes.length - 1].x}
                        cy={currentNodes[currentNodes.length - 1].y}
                        fill="none"
                        style={{ stroke: 'hsl(var(--foreground) / 0.25)' }}
                        strokeWidth="1"
                        initial={{ r: 4, opacity: 0.5 }}
                        animate={{ r: 20, opacity: 0 }}
                        transition={{ duration: 0.5 }}
                    />
                )}
            </svg>
        </div>
    );
}
