// The deploy wizard's rules, without React: which inputs a variable needs,
// which of them are missing, and what the API receives. Ported from the
// students' Vue wizard (NewDeploymentVariableView.vue, deployment.store.ts),
// where the same rules lived inside components and were only testable by
// clicking through.
//
// A variable comes from GET /apps/{id}/variables. The relevant fields:
//   source      'terraform' | 'packer'
//   type        the HCL type, e.g. 'string', 'number', 'bool', 'list(string)'
//   required    no HCL default
//   osType      an @openstack marker: 'network', 'flavor', ..., or 'file'
//   osMode      'id' | 'name' — what the picker stores
//   osMulti     several values
//   varScope    'all' | 'team' | 'user' — one value, one per team, one per member
//   fileExtensions  for osType 'file'
//   template_key    Packer only; more than one key means several images

const lower = (s) => String(s ?? '').toLowerCase();

export const isBool = (type) => ['bool', 'boolean'].includes(lower(type));
export const isNumber = (type) => ['number', 'int', 'integer'].includes(lower(type));
export const isList = (type) => /^(list|set|tuple|array)/.test(lower(type));
export const isFileVar = (v) => v?.osType === 'file';
export const hasPicker = (v) => Boolean(v?.osType) && v.osType !== 'file';

/** A variable's scope: 'all' (one value), 'team' (one per team) or 'user' (one per member); anything else counts as 'all'. */
export function scopeOf(v) {
    const s = v?.varScope || v?.osScope || 'all';
    return s === 'team' || s === 'user' ? s : 'all';
}

/** The local part of an address, as the platform derives a username from it. */
export const usernameOf = (email) => String(email ?? '').split('@')[0];

/**
 * The key a per-member value is stored under: "<team>-<username>". The API
 * checks the prefix against the team names (see _validate_scoped_user_input).
 */
export const userSlotKey = (teamName, email) => `${teamName}-${usernameOf(email)}`;

/**
 * List the slots a scoped variable needs a value for: team names, or
 * userSlotKey()s per member; empty for scope 'all'. `teams` is [{ name, emails }].
 */
export function slotKeys(v, teams) {
    const scope = scopeOf(v);
    if (scope === 'team') return teams.map(t => t.name);
    if (scope === 'user') return teams.flatMap(t => t.emails.map(e => userSlotKey(t.name, e)));
    return [];
}

/**
 * Whether the app builds several Packer images. Packer variables of a
 * multi-image app are nested per template; everything else is flat. Several
 * templates, or one that is not "default", is multi.
 */
export function isMultiImage(variables) {
    const keys = new Set(variables.filter(v => v.source === 'packer').map(v => v.template_key ?? 'default'));
    return keys.size > 1 || (keys.size === 1 && !keys.has('default'));
}

/**
 * The key under which the wizard keeps a variable's value ("<source>:<name>",
 * or "packer:<template>.<name>"). Packer variables of two images may share a
 * name, so they are kept apart by template.
 */
export function formKey(v, multi) {
    if (v.source === 'packer' && multi && (v.template_key ?? 'default') !== 'default') {
        return `packer:${v.template_key}.${v.name}`;
    }
    return `${v.source}:${v.name}`;
}

/**
 * The variables worth showing, once: the API lists a Packer variable per
 * template, and a template may repeat one. The first occurrence wins.
 */
export function dedupe(variables) {
    const seen = new Map();
    for (const v of variables ?? []) {
        const key = v.source === 'packer' ? `packer:${v.template_key ?? 'default'}.${v.name}` : `${v.source}:${v.name}`;
        if (!seen.has(key)) seen.set(key, v);
    }
    return [...seen.values()];
}

/**
 * The value a fresh form starts with: the HCL default, as the input shows it
 * (lists as "a, b", bools false, files {}). Scoped variables get an object
 * with one entry per slot, seeded with a scalar default.
 */
export function initialValue(v, teams) {
    if (isFileVar(v)) return {};
    const def = v.default;
    const shown = isList(v.type) && Array.isArray(def) ? def.join(', ') : def;
    if (scopeOf(v) !== 'all') {
        const seed = shown === undefined || shown === null || typeof shown === 'object' ? '' : shown;
        return Object.fromEntries(slotKeys(v, teams).map(k => [k, seed]));
    }
    if (shown === undefined || shown === null) return isBool(v.type) ? false : '';
    return shown;
}

/** initialValue() for every variable, keyed by formKey(). */
export function initialValues(variables, teams) {
    const multi = isMultiImage(variables);
    return Object.fromEntries(variables.map(v => [formKey(v, multi), initialValue(v, teams)]));
}

/**
 * What the form shows and sends: the defaults, overlaid with what was
 * entered. Derived on every render rather than kept in state, so another
 * version (other variables) or other teams (other slots) need no
 * synchronising: a slot that no longer exists is simply not asked for, a new
 * one starts from the default, and what was entered for a slot survives.
 */
export function effectiveValues(variables, entered, teams) {
    const multi = isMultiImage(variables);
    const out = {};
    for (const v of variables) {
        const key = formKey(v, multi);
        const init = initialValue(v, teams);
        const e = entered?.[key];
        if (scopeOf(v) === 'all') {
            out[key] = e !== undefined ? e : init;
        } else {
            const has = e && typeof e === 'object' ? e : {};
            out[key] = Object.fromEntries(Object.keys(init).map(k => [k, k in has ? has[k] : init[k]]));
        }
    }
    return out;
}

const isEmpty = (val) => val === undefined || val === null
    || (typeof val === 'string' && val.trim() === '')
    || (Array.isArray(val) && val.length === 0);

const isEmptyFile = (f) => !f || !f.content_b64;

/**
 * Name every required input still empty, as "name" or "name (slot)", so the
 * wizard can say exactly what is left. A scoped variable with no slots (no
 * teams yet) counts as missing.
 */
export function missingRequired(variables, values, teams) {
    const multi = isMultiImage(variables);
    const missing = [];
    for (const v of variables) {
        if (!v.required) continue;
        const val = values[formKey(v, multi)];
        if (isFileVar(v)) {
            const slots = scopeOf(v) === 'all' ? ['all'] : slotKeys(v, teams);
            for (const s of slots) if (isEmptyFile(val?.[s])) missing.push(scopeOf(v) === 'all' ? v.name : `${v.name} (${s})`);
            continue;
        }
        if (scopeOf(v) === 'all') {
            if (isEmpty(val)) missing.push(v.name);
            continue;
        }
        const slots = slotKeys(v, teams);
        if (slots.length === 0) missing.push(v.name);
        for (const s of slots) if (isEmpty(val?.[s])) missing.push(`${v.name} (${s})`);
    }
    return missing;
}

/** What the API gets for one input: lists from "a, b", numbers as numbers, everything else unchanged. */
export function coerce(v, raw) {
    if (isList(v.type) && typeof raw === 'string') return raw.split(',').map(s => s.trim()).filter(Boolean);
    if (isNumber(v.type) && raw !== '' && raw !== null && raw !== undefined) return Number(raw);
    return raw;
}

/**
 * Turn the wizard's state into the body of POST /deployments.
 *
 * Empty inputs are left out, not sent as "" or null: the worker would pass them
 * to OpenTofu as an explicit value and override the variable's HCL default.
 * Files travel apart from the variables (`files`), as the API wants them.
 * Packer values are nested per template only for a multi-image app.
 */
export function buildDeployment({ name, appId, releaseTag, course, credentialId, teams, variables, values }) {
    const multi = isMultiImage(variables);
    const userInputVar = { terraform: {}, packer: {} };
    const files = {};

    for (const v of variables) {
        const key = formKey(v, multi);
        const val = values[key];

        if (isFileVar(v)) {
            const filled = Object.fromEntries(Object.entries(val ?? {}).filter(([, f]) => !isEmptyFile(f)));
            if (Object.keys(filled).length) files[v.name] = filled;
            continue;
        }

        let out;
        if (scopeOf(v) === 'all') {
            if (isEmpty(val)) continue;
            out = coerce(v, val);
        } else {
            out = Object.fromEntries(Object.entries(val ?? {}).filter(([, x]) => !isEmpty(x)).map(([k, x]) => [k, coerce(v, x)]));
            if (!Object.keys(out).length) continue;
        }

        if (v.source === 'packer') {
            const tkey = v.template_key ?? 'default';
            if (multi) (userInputVar.packer[tkey] ??= {})[v.name] = out;
            else userInputVar.packer[v.name] = out;
        } else {
            userInputVar.terraform[v.name] = out;
        }
    }

    const body = {
        name: name.trim(),
        appId,
        releaseTag,
        course,
        credentialId,
        teams: teams.map(t => ({ name: t.name.trim(), emails: t.emails })),
        userInputVar,
    };
    if (Object.keys(files).length) body.files = files;
    return body;
}

// ── Teams ───────────────────────────────────────────────────────────────

/**
 * Put the students into `count` teams named "<namePrefix>-<n>", in the order
 * given, one after the other (round robin), so team sizes differ by at most one.
 */
export function distribute(emails, count, namePrefix = 'Team') {
    const n = Math.max(1, Math.floor(count) || 1);
    const teams = Array.from({ length: n }, (_, i) => ({ name: `${namePrefix}-${i + 1}`, emails: [] }));
    emails.forEach((e, i) => teams[i % n].emails.push(e));
    return teams;
}

/** The other way to ask for distribute(): "teams of three", i.e. ceil(n / size) teams filled round robin. */
export function teamsOfSize(emails, size, namePrefix = 'Team') {
    const s = Math.max(1, Math.floor(size) || 1);
    return distribute(emails, Math.max(1, Math.ceil(emails.length / s)), namePrefix);
}

/**
 * Say what keeps the teams from being sent: the API refuses the same things
 * (duplicate names, a person in two teams), but a sentence next to the field
 * beats a 422 after the last step.
 *
 * @returns {Array<{ kind: 'emptyName'|'duplicateName'|'duplicateMember', names?: string[], emails?: string[] }>}
 */
export function teamProblems(teams) {
    const problems = [];
    const names = teams.map(t => t.name.trim());
    if (names.some(n => !n)) problems.push({ kind: 'emptyName' });
    const dupNames = names.filter((n, i) => n && names.indexOf(n) !== i);
    if (dupNames.length) problems.push({ kind: 'duplicateName', names: [...new Set(dupNames)] });
    const all = teams.flatMap(t => t.emails);
    const dupMembers = all.filter((e, i) => all.indexOf(e) !== i);
    if (dupMembers.length) problems.push({ kind: 'duplicateMember', emails: [...new Set(dupMembers)] });
    return problems;
}

// ── Files ───────────────────────────────────────────────────────────────

/**
 * Turn a dropped File into what the API stores: standard base64
 * (cloud-init writes it with `encoding: b64`).
 *
 * @returns {Promise<{ name: string, content_b64: string, size: number, content_type: string|null }>}
 */
export function readFile(file) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onerror = () => reject(reader.error);
        reader.onload = () => {
            const url = String(reader.result);
            resolve({
                name: file.name,
                content_b64: url.slice(url.indexOf(',') + 1),
                size: file.size,
                content_type: file.type || null,
            });
        };
        reader.readAsDataURL(file);
    });
}
