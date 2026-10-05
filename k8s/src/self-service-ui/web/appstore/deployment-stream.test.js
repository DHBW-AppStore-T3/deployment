import { describe, it, expect } from 'vitest';
import { initialStreamState, MAX_LOG_LINES, parseFrame, parseFrames, reduce } from './deployment-stream.js';

describe('SSE frames', () => {
    it('split at blank lines and keep the unfinished rest', () => {
        const { frames, rest } = parseFrames('event: progress\nid: 7\ndata: {"phase":"GIT_CLONE"}\n\n: keepalive\n\nevent: log\ndata: {"mes');
        expect(frames).toEqual([{ event: 'progress', id: '7', data: { phase: 'GIT_CLONE' } }]);
        expect(rest).toBe('event: log\ndata: {"mes');
    });

    it('ignore comments and keep non-JSON data as text', () => {
        expect(parseFrame(': ping')).toBeNull();
        expect(parseFrame('event: log\ndata: plain')).toEqual({ event: 'log', id: null, data: 'plain' });
    });
});

describe('stream state', () => {
    const run = (...frames) => frames.reduce(reduce, initialStreamState);

    it('follows progress and ends with the task', () => {
        const s = run(
            { event: 'snapshot', data: { status: 'pending', current_phase: null, progress_pct: 0 } },
            { event: 'progress', data: { phase: 'TERRAFORM_APPLY', phase_index: 7, total_phases: 8, progress_pct: 80, phase_names: ['A', 'B'] } },
            { event: 'succeeded', data: {} },
        );
        expect(s).toMatchObject({ status: 'SUCCESS', phase: 'TERRAFORM_APPLY', phaseIndex: 7, totalPhases: 8, phaseNames: ['A', 'B'], progress: 100, ended: true });
    });

    it('a snapshot of a finished task ends the stream at once', () => {
        expect(run({ event: 'snapshot', data: { status: 'failed' } })).toMatchObject({ status: 'FAILED', ended: true });
    });

    it('keeps only the newest log lines', () => {
        const frames = Array.from({ length: MAX_LOG_LINES + 5 }, (_, i) => ({ event: 'log', data: { message: `l${i}`, timestamp: 't' } }));
        const s = run(...frames);
        expect(s.logs).toHaveLength(MAX_LOG_LINES);
        expect(s.logs[0].message).toBe('l5');
    });
});
