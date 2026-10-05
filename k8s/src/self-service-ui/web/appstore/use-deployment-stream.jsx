import { useEffect, useReducer } from 'react';
import { authHeaders } from '/providers/client.jsx';
import { initialStreamState, parseFrames, reduce } from '/appstore/deployment-stream.js';

// Live progress and log lines of a deployment's running task.
//
// fetch() and a stream reader rather than EventSource: EventSource cannot send
// the dev identity header, and in production the BFF's cookie travels with a
// same-origin fetch anyway. The reader keeps the last event id and sends it as
// Last-Event-ID when it reconnects, so a dropped connection resumes where it
// stopped. It reconnects with backoff until the task has ended or the view is
// gone.

const BASE_DELAY_MS = 1000;
const MAX_DELAY_MS = 15000;

/**
 * Follow a deployment's live stream while `enabled` (the detail view enables it
 * only while the deployment is in flight).
 *
 * @returns {object} the reduced stream state (see initialStreamState) plus
 *   `connection`: 'idle' | 'connecting' | 'live' | 'reconnecting' | 'error' | 'ended'.
 *   'error' means a 4xx, after which it does not retry.
 */
export function useDeploymentStream(deploymentId, { enabled = true } = {}) {
    const [state, dispatch] = useReducer(
        (s, a) => (a.type === 'reset' ? initialStreamState : a.type === 'connection' ? { ...s, connection: a.value } : reduce(s, a.frame)),
        { ...initialStreamState, connection: 'idle' },
    );

    useEffect(() => {
        if (!enabled || !deploymentId) return undefined;
        dispatch({ type: 'reset' });

        const base = window?.appconfig?.appstoreBaseUrl ?? '';
        const url = `${base.replace(/\/$/, '')}/deployments/${encodeURIComponent(deploymentId)}/stream`;
        let controller = null;
        let timer = null;
        let attempt = 0;
        let lastId = null;
        let ended = false;
        let stopped = false;

        const schedule = () => {
            if (stopped || ended) return;
            attempt += 1;
            dispatch({ type: 'connection', value: 'reconnecting' });
            timer = setTimeout(connect, Math.min(BASE_DELAY_MS * 2 ** (attempt - 1), MAX_DELAY_MS));
        };

        async function connect() {
            controller = new AbortController();
            dispatch({ type: 'connection', value: attempt ? 'reconnecting' : 'connecting' });
            let response;
            try {
                response = await fetch(url, {
                    signal: controller.signal,
                    headers: { Accept: 'text/event-stream', ...authHeaders(), ...(lastId ? { 'Last-Event-ID': lastId } : {}) },
                });
            } catch (err) {
                if (err?.name !== 'AbortError') schedule();
                return;
            }
            if (!response.ok || !response.body) {
                // A 4xx will not get better by asking again (gone, forbidden).
                if (response.status >= 400 && response.status < 500) {
                    dispatch({ type: 'connection', value: 'error' });
                    return;
                }
                schedule();
                return;
            }
            attempt = 0;
            dispatch({ type: 'connection', value: 'live' });
            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';
            try {
                for (;;) {
                    const { done, value } = await reader.read();
                    if (done) break;
                    buffer += decoder.decode(value, { stream: true });
                    const { frames, rest } = parseFrames(buffer);
                    buffer = rest;
                    for (const frame of frames) {
                        if (frame.id) lastId = frame.id;
                        if (['succeeded', 'failed', 'revoked'].includes(frame.event)) ended = true;
                        if (frame.event === 'snapshot' && ['SUCCESS', 'FAILED', 'CANCELLED'].includes(String(frame.data?.status).toUpperCase())) ended = true;
                        dispatch({ type: 'frame', frame });
                    }
                }
            } catch (err) {
                if (err?.name === 'AbortError') return;
            }
            if (ended) dispatch({ type: 'connection', value: 'ended' });
            else schedule();
        }

        connect();
        return () => {
            stopped = true;
            clearTimeout(timer);
            controller?.abort();
        };
    }, [deploymentId, enabled]);

    return state;
}
