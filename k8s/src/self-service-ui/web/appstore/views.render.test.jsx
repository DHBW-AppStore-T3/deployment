// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { cleanup, fireEvent, screen, waitFor } from '@testing-library/react';
import { renderWithProviders } from '/test/render-harness.jsx';

// Does each AppStore view render, with data in it? The same question the
// projects views are asked (see projects/views.render.test.jsx for why): not
// what a view looks like, only that it mounts, settles and shows its data.
// The API is the facade, answering from the fixtures below.

vi.mock('/appstore/api-appstore.jsx', async (importOriginal) => {
    const actual = await importOriginal();
    return { ...actual, useAppStoreApi: () => globalThis.__appstoreApi };
});

// The live stream reads fetch() as a stream; the views only consume its state.
vi.mock('/appstore/use-deployment-stream.jsx', () => ({
    useDeploymentStream: () => ({
        status: 'RUNNING', phase: 'TERRAFORM_APPLY', phaseIndex: 7, totalPhases: 8, phaseNames: [], progress: 80,
        logs: [{ timestamp: '2026-09-28T12:00:00Z', level: 'INFO', message: 'applying' }], ended: false, connection: 'live',
    }),
}));

const { Catalog } = await import('/appstore/catalog.jsx');
const { AppDetail } = await import('/appstore/app-detail.jsx');
const { RegisterApp } = await import('/appstore/register-app.jsx');
const { Credentials } = await import('/appstore/credentials.jsx');
const { Deployments } = await import('/appstore/deployments.jsx');
const { DeploymentDetail } = await import('/appstore/deployment-detail.jsx');
const { MyAccess } = await import('/appstore/my-access.jsx');
const { AdminApprovals } = await import('/appstore/admin-approvals.jsx');
const { DeployWizard } = await import('/appstore/wizard/deploy-wizard.jsx');

const ME = { userId: 'u1', email: 'faculty@cs.example', is_admin: true, is_dozent: true, can_register_apps: true, can_deploy: true };
const APP = {
    appId: 'a1', name: 'Online-IDE', description: '# Online-IDE\n\nCode-Server im Browser, eine VM pro Team.',
    git_link: 'https://github.com/example/online-ide', is_private: false, userId: 'u1', created_at: '2026-09-01T10:00:00Z',
    user: { userId: 'u1', email: 'faculty@cs.example', username: 'faculty', created_at: '2026-09-01T10:00:00Z' },
    versions: [
        { version: 'v1.0.2', sha: 'a'.repeat(40), commit: 'aaaaaaaa', type: 'tag', approved: true },
        { version: 'v1.1.0', sha: 'b'.repeat(40), commit: 'bbbbbbbb', type: 'tag', approved: false },
    ],
};
const CREDENTIAL = {
    credentialId: 'c1', auth_type: 'v3applicationcredential', auth_url: 'https://keystone.example/v3', project_id: 'p1',
    project_name: 'WWI23SEB Übungen', last_validated_at: '2026-09-28T10:00:00Z', last_validation_error: null, active_deployments: 1,
};
const VARIABLES = [
    { name: 'network_uuid', source: 'terraform', type: 'string', required: true, osType: 'network', osMode: 'id', description: 'Netz @openstack:network:id' },
    { name: 'flavor', source: 'terraform', type: 'string', required: false, default: 'm1.small', osType: 'flavor', osMode: 'name' },
    { name: 'greeting', source: 'terraform', type: 'string', required: false, varScope: 'team', default: 'Hallo' },
    { name: 'material', source: 'terraform', type: 'map(object)', required: false, osType: 'file', varScope: 'all', fileExtensions: ['pdf'] },
];
const DEPLOYMENT = {
    deploymentId: 'd1', name: 'Übung 1', appId: 'a1', userId: 'u1', releaseTag: 'v1.0.2', commit_sha: 'a'.repeat(40),
    course: 'group:wwi23seb', os_project_id: 'p1', status: 'success', created_at: '2026-09-28T11:00:00Z',
    user: APP.user, app: APP, permissions: { owner_view: true, operate: true },
    teams: [{ teamId: 't1', name: 'Team-1', members: [{ userId: 'u2', email: 'cs-student@cs.com', username: 'cs-student' }] }],
    latest_task: { taskId: 'k1', type: 'deploy', status: 'success', created_at: '2026-09-28T11:00:00Z' },
    outputs: { raw: { team_vms: { value: { 'Team-1': { code_server_url: 'http://203.0.113.10:8080' } }, sensitive: false }, user_accounts: { value: null, sensitive: true, redacted: true } } },
};
const ACCESS = {
    user_accounts: { 'Team-1-cs-student': { username: 'cs-student', auth: 's3cret', type: 'password', ip: '203.0.113.10', port: 8080 } },
    team_vms: { 'Team-1': { code_server_url: 'http://203.0.113.10:8080', floating_ip: '203.0.113.10' } },
};

function fakeApi(overrides = {}) {
    return {
        getMe: async () => ME,
        listApps: async () => [APP, { ...APP, appId: 'a2', name: 'pgAdmin', description: 'Datenbanken', is_private: true }],
        getApp: async () => APP,
        createApp: async () => APP,
        updateApp: async () => APP,
        deleteApp: async () => ({}),
        getVariables: async () => VARIABLES,
        listApprovals: async () => [{ approvalId: 'x1', appId: 'a1', version_tag: 'v1.1.0', commit_sha: 'b'.repeat(40), status: 'pending', created_at: '2026-09-28T09:00:00Z' }],
        submitVersion: async () => ({}),
        withdrawVersion: async () => ({}),
        listPendingApprovals: async () => [{ approvalId: 'x1', appId: 'a1', version_tag: 'v1.1.0', commit_sha: 'b'.repeat(40), status: 'pending', created_at: '2026-09-28T09:00:00Z', app: APP }],
        approveVersion: async () => ({}),
        rejectVersion: async () => ({}),
        listMyCourses: async () => [{ course: 'group:wwi23seb', display_name: 'WWI23SEB', description: '' }],
        listStudents: async () => ['anna@dhbw.de', 'ben@dhbw.de', 'cem@dhbw.de'],
        listMyAccess: async () => [{ deploymentId: 'd1', name: 'Übung 1', app_name: 'Online-IDE', course: 'group:wwi23seb', team_name: 'Team-1', status: 'success', ...ACCESS }],
        listCredentials: async () => [CREDENTIAL],
        saveCredential: async () => CREDENTIAL,
        saveCredentialFromYaml: async () => CREDENTIAL,
        testCredential: async () => CREDENTIAL,
        deleteCredential: async () => ({}),
        getQuota: async () => ({ compute: { instances: { used: 2, limit: 10, available: 8 } }, storage: {}, network: {} }),
        listResources: async (_id, kind) => (kind === 'network'
            ? [{ id: 'net-1', name: 'internal' }]
            : [{ id: 'f-1', name: 'm1.small', vcpus: 1, ram: 2048 }]),
        refreshResources: async () => ({}),
        listDeployments: async () => [DEPLOYMENT, { ...DEPLOYMENT, deploymentId: 'd2', name: 'Übung 2', status: 'running' }],
        getDeployment: async () => DEPLOYMENT,
        createDeployment: async (body) => { globalThis.__created = body; return { deploymentId: 'd9' }; },
        deleteDeployment: async () => ({ task_id: 'k2', status: 'destroying' }),
        pauseDeployment: async () => ({}),
        resumeDeployment: async () => ({}),
        listTasks: async () => [{ taskId: 'k1', deploymentId: 'd1', type: 'deploy', status: 'success', created_at: '2026-09-28T11:00:00Z', logs: '[{"timestamp":"2026-09-28T11:00:01Z","level":"INFO","message":"done"}]' }],
        listResourcesOf: async () => ({ resources: [{ address: 'openstack_compute_instance_v2.team_vm["Team-1"]', type: 'openstack_compute_instance_v2', category: 'instance', team: 'Team-1', provider_id: 's1', display_name: 'sim-team-1', lifecycle: { status: 'ACTIVE' }, addresses: [{ network: 'internal', fixed_ip: '10.0.0.10' }] }] }),
        redeployResource: async () => ({}),
        getMyDeploymentAccess: async () => ACCESS,
        resendAccess: async () => ({ status: 'sent' }),
        ...overrides,
    };
}

let consoleErrors = [];
beforeEach(() => {
    globalThis.__appstoreApi = fakeApi();
    globalThis.__created = null;
    consoleErrors = [];
    vi.spyOn(console, 'error').mockImplementation((...args) => { consoleErrors.push(args.join(' ')); });
});
afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
});

function expectNoRenderFailure() {
    expect(consoleErrors.filter(e => /Maximum update depth|is not defined|is not a function|Cannot read/.test(e))).toEqual([]);
}

describe('the AppStore views render', () => {
    it('the catalogue lists the apps and filters them', async () => {
        renderWithProviders(<Catalog />);
        expect(await screen.findByText('Online-IDE')).toBeTruthy();
        expect(screen.getByText('pgAdmin')).toBeTruthy();
        fireEvent.change(screen.getByPlaceholderText(/search/i), { target: { value: 'daten' } });
        await waitFor(() => expect(screen.queryByText('Online-IDE')).toBeNull());
        expectNoRenderFailure();
    });

    it('an app shows its description, versions and review state', async () => {
        renderWithProviders(<AppDetail params={{ appId: 'a1' }} />);
        expect(await screen.findByText('v1.0.2')).toBeTruthy();
        expect(screen.getByText('v1.1.0')).toBeTruthy();
        expect(await screen.findByText('In review')).toBeTruthy();
        expect(document.querySelector('h1')?.textContent).toBe('Online-IDE');
        expectNoRenderFailure();
    });

    it('registering an app renders its form', async () => {
        renderWithProviders(<RegisterApp />);
        expect(await screen.findByText(/public Git repository/)).toBeTruthy();
        expectNoRenderFailure();
    });

    it('credentials show their project and quota', async () => {
        renderWithProviders(<Credentials />);
        expect(await screen.findByText('WWI23SEB Übungen')).toBeTruthy();
        fireEvent.click(screen.getByText('Quota'));
        expect(await screen.findByText('2 / 10')).toBeTruthy();
        expectNoRenderFailure();
    });

    it('the deployment list shows every deployment with its status', async () => {
        renderWithProviders(<Deployments />);
        expect(await screen.findByText('Übung 1')).toBeTruthy();
        expect(screen.getByText('Übung 2')).toBeTruthy();
        expectNoRenderFailure();
    });

    it('a deployment shows the owner view with teams, resources and log', async () => {
        renderWithProviders(<DeploymentDetail params={{ deploymentId: 'd1' }} />);
        expect(await screen.findByText('Übung 1')).toBeTruthy();
        expect(screen.getByText(/Hidden \(sensitive\)/)).toBeTruthy();
        fireEvent.click(screen.getByRole('tab', { name: 'Teams' }));
        expect(await screen.findByText('cs-student@cs.com')).toBeTruthy();
        fireEvent.click(screen.getByRole('tab', { name: 'Infrastructure' }));
        expect(await screen.findByText('sim-team-1')).toBeTruthy();
        fireEvent.click(screen.getByRole('tab', { name: 'Log' }));
        expect(await screen.findByText(/done/)).toBeTruthy();
        expectNoRenderFailure();
    });

    it('a running deployment shows its live progress', async () => {
        globalThis.__appstoreApi = fakeApi({ getDeployment: async () => ({ ...DEPLOYMENT, status: 'running' }) });
        renderWithProviders(<DeploymentDetail params={{ deploymentId: 'd1' }} />);
        expect(await screen.findByText(/applying/)).toBeTruthy();
        expectNoRenderFailure();
    });

    it('a team member sees only their own access, the password hidden', async () => {
        globalThis.__appstoreApi = fakeApi({ getDeployment: async () => ({ ...DEPLOYMENT, outputs: null, permissions: { owner_view: false, operate: false } }) });
        renderWithProviders(<DeploymentDetail params={{ deploymentId: 'd1' }} />);
        expect(await screen.findByText('cs-student')).toBeTruthy();
        expect(screen.queryByText('s3cret')).toBeNull();
        expect(screen.queryByRole('button', { name: /Tear down/ })).toBeNull();
        expectNoRenderFailure();
    });

    it('"My access" lists the environments with the access data', async () => {
        renderWithProviders(<MyAccess />);
        expect(await screen.findByText('Übung 1')).toBeTruthy();
        expect(screen.getByText('cs-student')).toBeTruthy();
        fireEvent.click(screen.getByLabelText('Show'));
        expect(await screen.findByText('s3cret')).toBeTruthy();
        expectNoRenderFailure();
    });

    it('the review queue lists pending versions', async () => {
        renderWithProviders(<AdminApprovals />);
        expect(await screen.findByText('Online-IDE')).toBeTruthy();
        expect(screen.getByText(/Version v1.1.0 at/)).toBeTruthy();
        expectNoRenderFailure();
    });
});

describe('the deploy wizard', () => {
    it('walks from the basics to a deployment request', async () => {
        renderWithProviders(<DeployWizard params={{ appId: 'a1' }} />);
        const next = async () => {
            const button = await screen.findByRole('button', { name: 'Next' });
            await waitFor(() => expect(button.disabled).toBe(false));
            fireEvent.click(button);
        };

        fireEvent.change(await screen.findByLabelText(/^Name/), { target: { value: 'Übung 1' } });
        // Version, credential and course pick themselves: one of each is deployable.
        await next();

        fireEvent.click(await screen.findByRole('button', { name: 'Distribute' }));
        expect(await screen.findByDisplayValue('Team-2')).toBeTruthy();
        await next();

        // network_uuid is required and has no default: Next stays off until it is set.
        expect(await screen.findByText(/Reading the app|network_uuid/)).toBeTruthy();
        expect(screen.getByRole('button', { name: 'Next' }).disabled).toBe(true);
        expect(screen.getAllByText('network_uuid').length).toBeGreaterThan(0);
        expectNoRenderFailure();
    });
});
