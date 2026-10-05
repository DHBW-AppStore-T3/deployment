// The deployment live stream (GET /deployments/{id}/stream), without React.
// Ported from the students' useDeploymentStream.ts: the parsing and the state
// transitions live here as pure functions, the fetch loop in the hook
// (use-deployment-stream.jsx).
//
// The API sends Server-Sent Events. Each frame is lines of `event:`, `data:`
// and `id:`; `id` is the task_events row id, sent back as Last-Event-ID on a
// reconnect so the stream resumes instead of replaying. Events:
//   snapshot   the task's state at connect
//   progress   { phase, phase_index, total_phases, progress_pct, phase_names }
//   log        one log entry
//   succeeded | failed | revoked   the task ended; the stream closes

/** How many log lines the live view keeps; the full log is on the task. */
export const MAX_LOG_LINES = 200;

/**
 * Split a buffer into complete frames and the unfinished rest, which the
 * caller prepends to the next chunk.
 *
 * @returns {{ frames: Array<{ event: string, id: string|null, data: * }>, rest: string }}
 */
export function parseFrames(buffer) {
    const parts = buffer.split('\n\n');
    const rest = parts.pop() ?? '';
    return { frames: parts.map(parseFrame).filter(Boolean), rest };
}

/** Read one frame into `{ event, id, data }`; comments (`:` keepalives) and empty frames are null. */
export function parseFrame(raw) {
    if (!raw.trim()) return null;
    let event = 'message';
    let id = null;
    const data = [];
    for (const line of raw.split('\n')) {
        if (line.startsWith(':')) continue;
        if (line.startsWith('event:')) event = line.slice(6).trim();
        else if (line.startsWith('data:')) data.push(line.slice(5).trimStart());
        else if (line.startsWith('id:')) id = line.slice(3).trim();
    }
    if (!data.length && event === 'message') return null;
    return { event, id, data: parseData(data.join('\n')) };
}

/** A frame's data as JSON, or as the raw text if it is not JSON. */
function parseData(text) {
    if (!text) return null;
    try {
        return JSON.parse(text);
    } catch {
        return text;
    }
}

/** The stream state before the first frame; also what a reconnect to another deployment resets to. */
export const initialStreamState = {
    status: null,          // task status: PENDING, RUNNING, SUCCESS, FAILED, CANCELLED
    phase: null,
    phaseIndex: null,
    totalPhases: null,
    phaseNames: [],
    progress: null,
    logs: [],
    ended: false,
};

const TERMINAL = { succeeded: 'SUCCESS', failed: 'FAILED', revoked: 'CANCELLED' };

/**
 * Apply one parsed frame to the state (a pure reducer). A `progress` frame
 * implies RUNNING; a terminal event or a snapshot with a final status sets
 * `ended`; logs are capped at MAX_LOG_LINES. Unknown events are ignored.
 */
export function reduce(state, { event, data }) {
    switch (event) {
    case 'snapshot': {
        const status = String(data?.status ?? '').toUpperCase() || null;
        const ended = ['SUCCESS', 'FAILED', 'CANCELLED'].includes(status);
        return {
            ...state,
            status,
            phase: data?.current_phase ?? state.phase,
            progress: data?.progress_pct ?? state.progress,
            ended: state.ended || ended,
        };
    }
    case 'progress':
        return {
            ...state,
            status: state.status === 'PENDING' || !state.status ? 'RUNNING' : state.status,
            phase: data?.phase ?? state.phase,
            phaseIndex: data?.phase_index ?? state.phaseIndex,
            totalPhases: data?.total_phases ?? state.totalPhases,
            phaseNames: Array.isArray(data?.phase_names) && data.phase_names.length ? data.phase_names : state.phaseNames,
            progress: data?.progress_pct ?? state.progress,
        };
    case 'log': {
        const entry = {
            ...(data && typeof data === 'object' ? data : { message: String(data ?? '') }),
            timestamp: data?.iso_timestamp || data?.timestamp || new Date().toISOString(),
        };
        const logs = [...state.logs, entry];
        return { ...state, logs: logs.length > MAX_LOG_LINES ? logs.slice(-MAX_LOG_LINES) : logs };
    }
    default:
        if (TERMINAL[event]) {
            return { ...state, status: TERMINAL[event], ended: true, progress: event === 'succeeded' ? 100 : state.progress };
        }
        return state;
    }
}
