#!/usr/bin/env npx tsx
/**
 * CLI wrapper for GraphAccumulator.
 *
 * This script allows Python tests to use the same graph accumulation logic
 * as the frontend, ensuring a single source of truth.
 *
 * Usage:
 *   echo '[{"type": "node_start", "data": {...}}, ...]' | npx tsx scripts/graph-accumulator-cli.ts
 *
 * Input: JSON array of events on stdin, where each event has:
 *   - type: string (event type like 'node_start', 'edge_add', etc.)
 *   - data: object (event data payload)
 *
 * Output: JSON object with the final graph and verification results
 */

import { GraphAccumulator } from '../app/lib/graphAccumulator';
import * as fs from 'fs';

interface EventInput {
    type: string;
    data: Record<string, unknown>;
}

async function main() {
    // Read all input from stdin
    const input = fs.readFileSync(0, 'utf-8');

    let events: EventInput[];
    try {
        events = JSON.parse(input);
    } catch (e) {
        console.error('Failed to parse input JSON:', e);
        process.exit(1);
    }

    if (!Array.isArray(events)) {
        console.error('Input must be a JSON array of events');
        process.exit(1);
    }

    // Process events through the accumulator
    const accumulator = new GraphAccumulator();

    for (const event of events) {
        if (!event.type || typeof event.type !== 'string') {
            console.error('Each event must have a "type" string field');
            process.exit(1);
        }
        accumulator.handleEvent(event.type, event.data || {});
    }

    // Get the final graph and verification results
    const finalGraph = accumulator.getFinalGraph();
    const verification = accumulator.verifyIterationEdges();
    const errors = accumulator.getErrors();

    // Output the result
    const output = {
        graph: finalGraph,
        verification,
        errors,
        state: accumulator.getState(),
    };

    console.log(JSON.stringify(output, null, 2));
}

main().catch(e => {
    console.error('Error:', e);
    process.exit(1);
});
