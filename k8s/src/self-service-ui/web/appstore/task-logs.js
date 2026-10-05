// Reading a finished task's stored log for the task log tab of
// deployment-detail.jsx. Pure functions, unit-tested in task-logs.test.js.

/**
 * Split a finished task's log as the worker stores it (worker/job_queue.py): the
 * JSON list of log entries, and on failure a plain-text tail after it
 * ("[err] Error: ...", the commit). Either part may be missing.
 *
 * @returns {{ entries: object[], tail: string }} If the head is not valid JSON,
 *   the whole text is returned as `tail` so nothing is lost.
 */
export function parseTaskLogs(text) {
    const raw = String(text ?? '').trim();
    if (!raw) return { entries: [], tail: '' };
    const cut = raw.indexOf('\n\n[err]');
    const head = cut >= 0 ? raw.slice(0, cut) : raw;
    const tail = cut >= 0 ? raw.slice(cut).trim() : '';
    try {
        const parsed = JSON.parse(head);
        return { entries: Array.isArray(parsed) ? parsed : [], tail };
    } catch {
        return { entries: [], tail: raw };
    }
}

/** Format one log entry as a line of the log view: "12:03:04 INFO    [tool] message". */
export function logLine(entry) {
    const time = String(entry.timestamp ?? '').replace(/^.*T(\d\d:\d\d:\d\d).*$/, '$1');
    const tool = entry.tool ? `[${entry.tool}] ` : '';
    return `${time} ${String(entry.level ?? '').padEnd(7)} ${tool}${entry.message ?? ''}`;
}
