import i18n from '/i18n/index.js';

// The AppStore API is FastAPI, not Go: a failure carries `detail`, which is a
// sentence, a validation list, or an object with a machine-readable `code` or
// `reason` (see the API's routers). The shared apiErrorMessage() would turn the
// object into "[object Object]", so this area reads it itself and says what the
// code means. Codes without a translation fall back to the code, which is still
// more useful than nothing and shows up in a bug report verbatim.

// Codes (`code` or `reason`) that have a sentence of their own.
const KNOWN = new Set([
    'role_required', 'course_not_taught', 'not_in_course', 'member_in_several_teams',
    'duplicate_team_name', 'role_provider_unavailable', 'openstack_credentials_invalid',
    'openstack_credentials_missing', 'openstack_credentials_missing_for_project',
    'openstack_credentials_locked', 'openstack_credential_not_found', 'openstack_unavailable',
    'openstack_list_failed', 'version_not_approved', 'version_moved', 'deployment_operate_forbidden',
    'deployment_view_forbidden', 'deployment_owner_view_forbidden', 'app_view_forbidden',
    'git_host_not_allowed', 'smtp_disabled', 'smtp_send_failed', 'no_successful_deploy',
    'identity_provider_unavailable',
]);

/**
 * Turn a FastAPI `detail` into one sentence: a string as is, a 422 validation
 * list as "field.path: msg; ...", a known `code`/`reason` via its i18n text
 * (appstore.errors.<code>), anything else as the code or its JSON.
 *
 * @param {*} detail the `detail` of the error body, may be missing
 * @param {number} [status] HTTP status, used only when there is no detail
 */
export function describeDetail(detail, status) {
    if (detail == null) return status ? `HTTP ${status}` : i18n.t('appstore.errors.unknown');
    if (typeof detail === 'string') return detail;
    if (Array.isArray(detail)) {
        // Request validation (422): [{ loc: ['body','teams',0,'emails',1], msg }]
        return detail.map(d => [d?.loc?.slice(1).join('.'), d?.msg].filter(Boolean).join(': ')).join('; ');
    }
    const code = detail.code ?? detail.reason;
    if (KNOWN.has(code)) {
        return i18n.t(`appstore.errors.${code}`, {
            emails: (detail.emails ?? []).join(', '),
            teams: (detail.teams ?? []).join(', '),
            cause: detail.cause ? i18n.t(`appstore.errors.causes.${detail.cause}`, { defaultValue: detail.cause }) : '',
            count: detail.active_deployments ?? 0,
            version: detail.version ?? '',
        });
    }
    return code ?? JSON.stringify(detail);
}

/**
 * Build the Error the facade throws from a hey-api result: a message for the
 * person, and the status and raw detail for code that has to branch on them (a
 * 409 refreshes instead of blaming the input, see useApiMutation).
 *
 * @returns {Error & { status?: number, detail?: * }}
 */
export function appstoreError(res) {
    const status = res?.response?.status;
    const detail = res?.error?.detail ?? res?.error;
    const err = new Error(describeDetail(detail, status));
    err.status = status;
    err.detail = detail;
    return err;
}

/** Whether a hey-api result is a failure: an `error` payload or a non-2xx response. */
export function failed(res) {
    return Boolean(res?.error) || (res?.response && !res.response.ok);
}
