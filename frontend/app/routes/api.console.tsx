// API endpoint for writing console logs to a local file with size management.
// Maintains a 500KB rolling log file that auto-truncates when the limit is exceeded.

import { type ActionFunctionArgs } from 'react-router';
import { json } from '~/lib/routerResponse';
import fs from 'fs';
import path from 'path';

const MAX_SIZE = 500 * 1024; // 500KB
const KEEP_SIZE = 250 * 1024; // Keep last 250KB when truncating
const LOG_FILE = path.join(process.cwd(), '..', 'logs', 'console.log');

export async function action({ request }: ActionFunctionArgs) {
    // Only allow logging in development mode
    if (process.env.NODE_ENV !== 'development') {
        return json({ success: false, error: 'Logging disabled in production' }, { status: 403 });
    }
    
    try {
        const { type, args } = await request.json();
        
        // Ensure logs directory exists
        const logsDir = path.dirname(LOG_FILE);
        if (!fs.existsSync(logsDir)) {
            fs.mkdirSync(logsDir, { recursive: true });
        }
        
        // Check file size and truncate if needed
        if (fs.existsSync(LOG_FILE)) {
            const stats = fs.statSync(LOG_FILE);
            if (stats.size > MAX_SIZE) {
                // Read file and keep only the last portion
                const content = fs.readFileSync(LOG_FILE, 'utf-8');
                const truncated = content.slice(-KEEP_SIZE);
                fs.writeFileSync(LOG_FILE, `--- Log truncated at ${new Date().toISOString()} ---\n${truncated}`);
            }
        }
        
        // Format log entry with timestamp
        const timestamp = new Date().toISOString();
        const logEntry = `[${timestamp}] [${type.toUpperCase()}] ${JSON.stringify(args)}\n`;
        
        // Append to log file
        fs.appendFileSync(LOG_FILE, logEntry);
        
        return json({ success: true });
    } catch (error) {
        console.error('Failed to write console log:', error);
        return json({ success: false, error: String(error) }, { status: 500 });
    }
}