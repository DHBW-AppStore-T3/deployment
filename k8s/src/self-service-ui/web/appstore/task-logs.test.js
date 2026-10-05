import { describe, it, expect } from 'vitest';
import { logLine, parseTaskLogs } from './task-logs.js';

describe('task logs', () => {
    it('read the entries and the failure tail', () => {
        const text = '[{"timestamp":"2026-09-28T12:03:04Z","level":"INFO","message":"go"}]\n\n[err] Error: boom\nCommit: abc';
        const { entries, tail } = parseTaskLogs(text);
        expect(entries).toHaveLength(1);
        expect(tail).toBe('[err] Error: boom\nCommit: abc');
        expect(logLine({ ...entries[0], tool: 'tofu' })).toBe('12:03:04 INFO    [tofu] go');
    });

    it('keep a plain message as the tail', () => {
        expect(parseTaskLogs('Task failed: worker lost')).toEqual({ entries: [], tail: 'Task failed: worker lost' });
        expect(parseTaskLogs(null)).toEqual({ entries: [], tail: '' });
    });
});
