// Deployment status helpers shared by the deployment list, the detail view
// and "Meine Zugänge": which statuses are busy, which actions each allows,
// and the status badge.
import { Badge, Loader } from '@mantine/core';
import { useTranslation } from 'react-i18next';

// Deployment statuses as the API derives them from the latest task
// (crud/deployments.derive_status), and what may be done in each. The lists
// mirror services/lifecycle.py so the UI offers only what the API accepts;
// the API still decides.

/** Statuses with a task still running; views poll or stream while a deployment is in one. */
export const IN_FLIGHT = new Set(['pending', 'running', 'destroying', 'pausing', 'resuming']);

const ALLOWED = {
    success: ['destroy', 'pause'],
    failed: ['destroy', 'delete'],
    cancelled: ['delete'],
    paused: ['resume', 'destroy'],
    pause_failed: ['pause', 'resume', 'destroy'],
    resume_failed: ['resume', 'pause', 'destroy'],
    // Retrying the redeploy happens per VM in the infrastructure tab.
    redeploy_failed: ['pause', 'destroy'],
};

/** The actions ('destroy', 'delete', 'pause', 'resume') the UI offers for a status, as a Set. */
export function allowedActions(status) {
    return new Set(ALLOWED[status] ?? []);
}

const COLOR = {
    success: 'green',
    failed: 'red',
    pause_failed: 'red',
    resume_failed: 'red',
    redeploy_failed: 'red',
    cancelled: 'gray',
    paused: 'yellow',
    destroyed: 'gray',
};

const KNOWN = new Set([...IN_FLIGHT, ...Object.keys(COLOR)]);

/**
 * Coloured badge for a deployment status, with a spinner while it is in flight.
 * An unknown status is shown verbatim rather than as a missing translation key.
 */
export function StatusBadge({ status }) {
    const { t } = useTranslation();
    const s = status || 'none';
    const busy = IN_FLIGHT.has(s);
    return (
        <Badge color={busy ? 'blue' : COLOR[s] ?? 'gray'} variant="light"
            leftSection={busy ? <Loader size={10} color="blue" /> : null}>
            {KNOWN.has(s) || s === 'none' ? t(`appstore.status.${s}`) : s}
        </Badge>
    );
}
