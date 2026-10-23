// TanStack Query keys of the AppStore section. Every query and every
// mutation's `invalidates` list in web/appstore takes its keys from here.

/**
 * The cached server state of the AppStore section, named in one place so a
 * write invalidates exactly what it changed. Arrays, so a prefix invalidates
 * everything below it (`['appstore','deployments']` drops the list and every
 * detail).
 */
export const appstoreKeys = {
    me: () => ['appstore', 'me'],
    apps: () => ['appstore', 'apps'],
    app: (id) => ['appstore', 'apps', id],
    variables: (id, version) => ['appstore', 'apps', id, 'variables', version],
    runtime: (id, version) => ['appstore', 'apps', id, 'runtime', version],
    approvals: (id) => ['appstore', 'apps', id, 'approvals'],
    pendingApprovals: () => ['appstore', 'approvals', 'pending'],
    deployments: () => ['appstore', 'deployments'],
    deployment: (id) => ['appstore', 'deployments', id],
    deploymentTasks: (id) => ['appstore', 'deployments', id, 'tasks'],
    deploymentResources: (id) => ['appstore', 'deployments', id, 'resources'],
    myDeploymentAccess: (id) => ['appstore', 'deployments', id, 'my-access'],
    myAccess: () => ['appstore', 'my-access'],
    courses: () => ['appstore', 'courses'],
    students: (course) => ['appstore', 'courses', course, 'students'],
    credentials: () => ['appstore', 'credentials'],
    quota: (credentialId) => ['appstore', 'credentials', credentialId, 'quota'],
    resources: (credentialId, kind, filter) => ['appstore', 'credentials', credentialId, 'resources', kind, filter ?? null],
};
