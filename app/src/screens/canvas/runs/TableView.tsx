// TableView component renders array data in a table format
// Automatically detects columns from the data structure
// Reusable across different workflow nodes

import { useMemo } from 'react';

interface TableViewProps {
    data: any;
    maxRows?: number; // Maximum rows to display (default: 100)
}

export const TableView = ({ data, maxRows = 100 }: TableViewProps) => {
    // Extract table data and columns
    const { rows, columns, totalRows } = useMemo(() => {
        // Helper function to find array in data structure
        const findArray = (data: any): any[] => {
            // Case 1: Data is directly an array
            if (Array.isArray(data)) {
                return data;
            }
            // Case 2: Data has a "data" property with an array inside
            if (data?.data && typeof data.data === 'object') {
                const arrayProp = Object.values(data.data).find(
                    val => Array.isArray(val) && val.length > 0
                );
                if (arrayProp && Array.isArray(arrayProp)) {
                    return arrayProp;
                }
            }
            // Case 3: Find any array property at the top level
            if (data && typeof data === 'object') {
                const arrayProp = Object.values(data).find(
                    val => Array.isArray(val) && val.length > 0
                );
                if (arrayProp && Array.isArray(arrayProp)) {
                    return arrayProp;
                }
            }
            return [];
        };

        const dataArray = findArray(data);

        // Limit rows for performance
        const limitedRows = dataArray.slice(0, maxRows);

        // Extract columns from first row
        if (limitedRows.length === 0) {
            return { rows: [], columns: [], totalRows: 0 };
        }

        const firstRow = limitedRows[0];

        // Check if rows are primitives (strings, numbers, booleans)
        const isPrimitive = typeof firstRow !== 'object' || firstRow === null;

        if (isPrimitive) {
            // For arrays of primitives, convert to objects with a 'value' property
            const objectRows = limitedRows.map(val => ({ value: val }));
            return { rows: objectRows, columns: ['value'], totalRows: dataArray.length };
        }

        // For arrays of objects, extract keys from first row
        const cols = Object.keys(firstRow);
        return { rows: limitedRows, columns: cols, totalRows: dataArray.length };
    }, [data, maxRows]);

    // Render cell value (handles nested objects, arrays, null, undefined)
    const renderCellValue = (value: any): string => {
        if (value === null) return 'null';
        if (value === undefined) return 'undefined';
        if (typeof value === 'object') {
            try {
                return JSON.stringify(value);
            } catch {
                return String(value);
            }
        }
        return String(value);
    };

    if (rows.length === 0) {
        return (
            <div className="text-center text-muted-foreground dark:text-zinc-500 text-sm py-8">
                No table data available
            </div>
        );
    }

    const isTruncated = totalRows > maxRows;

    return (
        <div className="space-y-2">
            <div className="overflow-x-auto overflow-y-auto max-h-[600px] border border-border/50 dark:border-zinc-800/50 rounded-lg">
                <table className="min-w-full text-xs">
                    <thead className="bg-card/50 sticky top-0 z-10">
                        <tr>
                            {columns.map((col) => (
                                <th
                                    key={col}
                                    className="px-3 py-2 text-left font-semibold text-muted-foreground border-b border-border/50 dark:border-zinc-800/50 whitespace-nowrap"
                                >
                                    {col}
                                </th>
                            ))}
                        </tr>
                    </thead>
                    <tbody>
                        {rows.map((row, rowIndex) => (
                            <tr
                                key={rowIndex}
                                className="border-b border-border/30 dark:border-zinc-800/30 hover:bg-accent dark:hover:bg-zinc-800/20 transition-colors"
                            >
                                {columns.map((col) => {
                                    const cellText = renderCellValue(row[col]);
                                    return (
                                        <td
                                            key={`${rowIndex}-${col}`}
                                            className="px-3 py-2 text-foreground/80 font-mono align-top"
                                        >
                                            <div className="max-w-xs truncate" title={cellText}>
                                                {cellText}
                                            </div>
                                        </td>
                                    );
                                })}
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>

            {isTruncated && (
                <div className="text-xs text-muted-foreground dark:text-zinc-500 text-center py-1">
                    Showing first {maxRows} rows of {totalRows}
                </div>
            )}

            <div className="text-xs text-muted-foreground/70 dark:text-zinc-600">
                {rows.length} row{rows.length !== 1 ? 's' : ''} × {columns.length} column{columns.length !== 1 ? 's' : ''}
            </div>
        </div>
    );
};
