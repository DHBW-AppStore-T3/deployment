// The AppStore API facade over the generated @dhbw-cloud/appstore-client SDK.
// Every AppStore view calls the API through useAppStoreApi(), never the SDK.
import { useMemo } from 'react';
import { useClient } from '/providers/client.jsx';
import { appstoreError, failed } from '/appstore/errors.js';
// Named imports, not `sdk.<op>`: a missing named export fails the build, a
// property access on a namespace only fails in the browser.
import {
    addTeamMember, approveVersion, cancelDeployment, createApp, createDeployment, deactivateApp, deleteApp, deleteDeployment,
    deleteMyCredential, getApp, getAppRuntime, getAppVariables, getDeployment, getMyDeploymentAccess,
    getMe, getProjectQuota, listAvailabilityZones, listCourseStudents, listDeploymentResources,
    listDeploymentTasks, listDeployments, listApps, listFlavors, listFloatingIpPools, listImages,
    listKeypairs, listMyAccess, listMyCourses, listMyCredentials, listNetworks, listPendingVersions,
    listRouters, listSecurityGroups, listSubnets, listVersionApprovals, listVolumes,
    pauseDeployment, redeployDeploymentResource, refreshResourceCache, rejectVersion,
    removeTeamMember, resendAccessMail, resumeDeployment, revokeVersion, saveMyCredential,
    saveMyCredentialFromYaml, submitVersion, testMyCredential, updateApp, withdrawVersion,
} from '@dhbw-cloud/appstore-client';

// useAppStoreApi is to this section what useZonesApi is to DNS: the one place
// that knows the transport. Every call returns plain data or throws an Error
// whose message is a sentence (errors.js), with `status` and `detail` attached.
// Views never see the hey-api envelope.

/** Return a hey-api result's data, or throw appstoreError(res) if it failed. */
function unwrap(res) {
    if (failed(res)) throw appstoreError(res);
    return res?.data;
}

const JSON_HEADERS = { 'Content-Type': 'application/json' };

// The resource kinds the wizard's pickers offer (`@openstack:<kind>` markers),
// each mapped to its list operation.
const RESOURCE_LISTS = {
    network: listNetworks,
    subnet: listSubnets,
    flavor: listFlavors,
    image: listImages,
    keypair: listKeypairs,
    security_group: listSecurityGroups,
    floating_ip_pool: listFloatingIpPools,
    volume: listVolumes,
    router: listRouters,
    availability_zone: listAvailabilityZones,
};

/** The OpenStack resource kinds api.listResources accepts. */
export const RESOURCE_KINDS = Object.keys(RESOURCE_LISTS);

/**
 * The AppStore API as an object of plain async methods, memoised per client so
 * it can sit in hook dependency lists and serve as a query function directly.
 * Grouped below by area; the names follow the views, not the operation ids.
 */
export function useAppStoreApi() {
    const client = useClient('appstore');

    return useMemo(() => {
        const call = async (op, opts = {}) => unwrap(await op({ client, ...opts }));
        const body = (b) => ({ body: b, headers: JSON_HEADERS });

        return {
            // ── Catalogue ────────────────────────────────────────────────
            listApps: () => call(listApps, { query: { limit: 500 } }),
            getApp: (appId) => call(getApp, { path: { app_id: appId } }),
            createApp: (app) => call(createApp, body(app)),
            updateApp: (appId, changes) => call(updateApp, { path: { app_id: appId }, ...body(changes) }),
            deleteApp: (appId) => call(deleteApp, { path: { app_id: appId } }),
            deactivateApp: (appId) => call(deactivateApp, { path: { app_id: appId } }),
            getVariables: (appId, version) => call(getAppVariables, { path: { app_id: appId }, query: { version } }),
            // How a version runs: 'kubernetes' (pods) or 'openstack-vm'.
            getRuntime: (appId, version) => call(getAppRuntime, { path: { app_id: appId }, query: { version } }),

            // ── Version approvals ────────────────────────────────────────
            listApprovals: (appId) => call(listVersionApprovals, { path: { app_id: appId } }),
            submitVersion: (appId, tag, notes) =>
                call(submitVersion, { path: { app_id: appId, version_tag: tag }, ...body({ notes: notes || null }) }),
            withdrawVersion: (appId, tag) => call(withdrawVersion, { path: { app_id: appId, version_tag: tag } }),
            listPendingApprovals: () => call(listPendingVersions),
            approveVersion: (appId, tag) => call(approveVersion, { path: { app_id: appId, version_tag: tag } }),
            rejectVersion: (appId, tag, reason) =>
                call(rejectVersion, { path: { app_id: appId, version_tag: tag }, ...body({ rejection_reason: reason }) }),
            revokeVersion: (appId, tag, reason) =>
                call(revokeVersion, { path: { app_id: appId, version_tag: tag }, ...body({ rejection_reason: reason }) }),

            // ── The caller ───────────────────────────────────────────────
            getMe: () => call(getMe),

            // ── Courses and "Meine Zugänge" ──────────────────────────────
            listMyCourses: () => call(listMyCourses),
            listStudents: (course) => call(listCourseStudents, { path: { course } }),
            listMyAccess: () => call(listMyAccess),

            // ── OpenStack credentials, picker, quota ─────────────────────
            listCredentials: () => call(listMyCredentials),
            saveCredential: (payload) => call(saveMyCredential, body(payload)),
            saveCredentialFromYaml: (cloudsYaml, cloudName) =>
                call(saveMyCredentialFromYaml, body({ clouds_yaml: cloudsYaml, cloud_name: cloudName || null })),
            testCredential: (id) => call(testMyCredential, { path: { credential_id: id } }),
            deleteCredential: (id) => call(deleteMyCredential, { path: { credential_id: id } }),
            getQuota: (id) => call(getProjectQuota, { path: { credential_id: id } }),
            listResources: (id, kind, query) => {
                const op = RESOURCE_LISTS[kind];
                if (!op) throw new Error(`unknown resource kind ${kind}`);
                return call(op, { path: { credential_id: id }, query });
            },
            refreshResources: (id, kind) =>
                call(refreshResourceCache, { path: { credential_id: id }, query: kind ? { kind } : undefined }),

            // ── Deployments ──────────────────────────────────────────────
            listDeployments: () => call(listDeployments, { query: { limit: 500 } }),
            getDeployment: (id) => call(getDeployment, { path: { deployment_id: id } }),
            createDeployment: (deployment) => call(createDeployment, body(deployment)),
            deleteDeployment: (id) => call(deleteDeployment, { path: { deployment_id: id } }),
            pauseDeployment: (id) => call(pauseDeployment, { path: { deployment_id: id } }),
            cancelDeployment: (id) => call(cancelDeployment, { path: { deployment_id: id } }),
            resumeDeployment: (id) => call(resumeDeployment, { path: { deployment_id: id } }),
            listTasks: (id) => call(listDeploymentTasks, { path: { deployment_id: id } }),
            listResourcesOf: (id, refresh = true) =>
                call(listDeploymentResources, { path: { deployment_id: id }, query: { refresh } }),
            redeployResource: (id, address) =>
                call(redeployDeploymentResource, { path: { deployment_id: id, address } }),
            getMyDeploymentAccess: (id) => call(getMyDeploymentAccess, { path: { deployment_id: id } }),
            resendAccess: (id, teamId, userId) =>
                call(resendAccessMail, { path: { deployment_id: id, team_id: teamId, user_id: userId } }),
            addTeamMember: (teamId, email) => call(addTeamMember, { path: { team_id: teamId }, ...body({ email }) }),
            removeTeamMember: (teamId, email) => call(removeTeamMember, { path: { team_id: teamId, email } }),
        };
    }, [client]);
}
