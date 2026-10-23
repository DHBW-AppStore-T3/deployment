import { describe, it, expect } from 'vitest';
import {
    buildDeployment, dedupe, distribute, effectiveValues, formKey, hasPicker, initialValues, isEnumVar, isMultiImage, missingRequired,
    scopeOf, slotKeys, teamProblems, teamsOfSize, userSlotKey,
} from './wizard-logic.js';

const tf = (name, extra = {}) => ({ name, source: 'terraform', type: 'string', required: false, ...extra });
const pk = (name, extra = {}) => ({ name, source: 'packer', type: 'string', required: false, ...extra });

const TEAMS = [
    { name: 'Team-1', emails: ['anna@dhbw.de', 'ben@dhbw.de'] },
    { name: 'Team-A', emails: ['cem@dhbw.de'] },
];

describe('scopes', () => {
    it('reads varScope, then osScope, else all', () => {
        expect(scopeOf(tf('a'))).toBe('all');
        expect(scopeOf(tf('a', { varScope: 'team' }))).toBe('team');
        expect(scopeOf(tf('a', { osScope: 'user' }))).toBe('user');
        expect(scopeOf(tf('a', { varScope: 'nonsense' }))).toBe('all');
    });

    it('has one slot per team or per member', () => {
        expect(slotKeys(tf('a', { varScope: 'team' }), TEAMS)).toEqual(['Team-1', 'Team-A']);
        expect(slotKeys(tf('a', { varScope: 'user' }), TEAMS)).toEqual(['Team-1-anna', 'Team-1-ben', 'Team-A-cem']);
        expect(userSlotKey('Team-A', 'x.y@dhbw.de')).toBe('Team-A-x.y');
    });
});

describe('initial values and slots', () => {
    it('start from the HCL default, lists as "a, b"', () => {
        const vars = [
            tf('flavor', { default: 'm1.small' }),
            tf('ports', { type: 'list(number)', default: [80, 443] }),
            tf('debug', { type: 'bool' }),
            tf('greeting', { varScope: 'team', default: 'hi' }),
        ];
        expect(initialValues(vars, TEAMS)).toEqual({
            'terraform:flavor': 'm1.small',
            'terraform:ports': '80, 443',
            'terraform:debug': false,
            'terraform:greeting': { 'Team-1': 'hi', 'Team-A': 'hi' },
        });
    });
});

describe('effective values', () => {
    it('are the defaults overlaid with what was entered, per current slot', () => {
        const vars = [tf('flavor', { default: 'small' }), tf('pw', { varScope: 'user', default: 'x' })];
        const entered = { 'terraform:flavor': 'large', 'terraform:pw': { 'Team-1-anna': 'a', 'Gone-bob': 'b' }, 'terraform:old': 1 };

        expect(effectiveValues(vars, entered, TEAMS)).toEqual({
            'terraform:flavor': 'large',
            'terraform:pw': { 'Team-1-anna': 'a', 'Team-1-ben': 'x', 'Team-A-cem': 'x' },
        });
    });
});

describe('required inputs', () => {
    it('are named with their slot', () => {
        const vars = [
            tf('network', { required: true }),
            tf('pw', { required: true, varScope: 'user' }),
            tf('file', { required: true, osType: 'file', varScope: 'all' }),
            tf('optional'),
        ];
        const values = { 'terraform:network': '', 'terraform:pw': { 'Team-1-anna': 'x' }, 'terraform:file': {} };

        expect(missingRequired(vars, values, TEAMS)).toEqual(['network', 'pw (Team-1-ben)', 'pw (Team-A-cem)', 'file']);
    });

    it('a scoped variable without any team is missing as a whole', () => {
        expect(missingRequired([tf('pw', { required: true, varScope: 'team' })], {}, [])).toEqual(['pw']);
    });
});

describe('the deployment body', () => {
    const base = { name: ' Übung 1 ', appId: 'a1', releaseTag: 'v1', course: 'group:wwi23seb', credentialId: 'c1', teams: TEAMS };

    it('leaves empty inputs out so the HCL default applies, and coerces types', () => {
        const variables = [
            tf('network', { osType: 'network' }),
            tf('empty'),
            tf('ports', { type: 'list(number)' }),
            tf('count', { type: 'number' }),
            tf('pw', { varScope: 'user' }),
            tf('doc', { osType: 'file' }),
            pk('flavor'),
        ];
        const values = {
            'terraform:network': 'net-1',
            'terraform:empty': '  ',
            'terraform:ports': '80, 443,',
            'terraform:count': '3',
            'terraform:pw': { 'Team-1-anna': 'a', 'Team-1-ben': '' },
            'terraform:doc': { all: { name: 'a.pdf', content_b64: 'QQ==', size: 1 }, other: { name: 'b' } },
            'packer:flavor': 'm1.small',
        };

        expect(buildDeployment({ ...base, variables, values })).toEqual({
            name: 'Übung 1',
            appId: 'a1',
            releaseTag: 'v1',
            course: 'group:wwi23seb',
            credentialId: 'c1',
            teams: TEAMS,
            userInputVar: {
                terraform: { network: 'net-1', ports: ['80', '443'], count: 3, pw: { 'Team-1-anna': 'a' } },
                packer: { flavor: 'm1.small' },
            },
            files: { doc: { all: { name: 'a.pdf', content_b64: 'QQ==', size: 1 } } },
        });
    });

    it('nests Packer values per image for multi-image apps', () => {
        const variables = dedupe([
            pk('flavor', { template_key: 'web' }),
            pk('flavor', { template_key: 'db' }),
            pk('flavor', { template_key: 'db' }),
        ]);
        expect(variables).toHaveLength(2);
        expect(isMultiImage(variables)).toBe(true);
        const values = { [formKey(variables[0], true)]: 'a', [formKey(variables[1], true)]: 'b' };

        expect(buildDeployment({ ...base, variables, values }).userInputVar.packer).toEqual({ web: { flavor: 'a' }, db: { flavor: 'b' } });
    });
});

describe('teams', () => {
    const emails = ['a@x', 'b@x', 'c@x', 'd@x', 'e@x'];

    it('are filled round robin, sizes differ by at most one', () => {
        expect(distribute(emails, 2).map(t => t.emails)).toEqual([['a@x', 'c@x', 'e@x'], ['b@x', 'd@x']]);
        expect(teamsOfSize(emails, 2).map(t => t.name)).toEqual(['Team-1', 'Team-2', 'Team-3']);
        expect(distribute([], 0)).toEqual([{ name: 'Team-1', emails: [] }]);
    });

    it('name what the API would refuse', () => {
        expect(teamProblems([{ name: 'A', emails: ['x'] }, { name: 'A', emails: ['x'] }, { name: ' ', emails: [] }])).toEqual([
            { kind: 'emptyName' },
            { kind: 'duplicateName', names: ['A'] },
            { kind: 'duplicateMember', emails: ['x'] },
        ]);
        expect(teamProblems(TEAMS)).toEqual([]);
    });
});

describe('apps that run as pods', () => {
    it('treats a fixed choice as a select, not as an OpenStack picker', () => {
        const v = tf('cpu_class', { osType: 'enum', values: ['small', 'medium'], default: 'small' });
        expect(isEnumVar(v)).toBe(true);
        expect(hasPicker(v)).toBe(false);
        expect(hasPicker(tf('flavor', { osType: 'flavor' }))).toBe(true);
    });

    it('sends no credential for a pod deployment', () => {
        const base = { name: 'd', appId: 'a', releaseTag: 'v1', course: 'group:c', teams: [], variables: [], values: {} };
        expect('credentialId' in buildDeployment({ ...base, credentialId: null })).toBe(false);
        expect(buildDeployment({ ...base, credentialId: 'cred-1' }).credentialId).toBe('cred-1');
    });
});
