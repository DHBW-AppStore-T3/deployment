// Hooks shared by the AppStore views: the caller's rights as the API reports them.
import { useQuery } from '@tanstack/react-query';
import { useAppStoreApi } from '/appstore/api-appstore.jsx';
import { appstoreKeys } from '/appstore/query-keys.js';

/**
 * The caller's rights as the API sees them (GET /me). Decides what the views
 * OFFER; every action is checked by the API anyway. Until it has answered,
 * nothing privileged is offered (all flags are false while loading).
 *
 * @returns {{ query: object, me: object|undefined, isAdmin: boolean, canDeploy: boolean, canRegisterApps: boolean }}
 *   the raw query (for loading/error state), the /me payload, and the flags derived from it.
 */
export function useMe() {
    const api = useAppStoreApi();
    const query = useQuery({ queryKey: appstoreKeys.me(), queryFn: api.getMe, staleTime: 60_000 });
    const me = query.data;
    return {
        query,
        me,
        isAdmin: Boolean(me?.is_admin),
        canDeploy: Boolean(me?.can_deploy),
        canRegisterApps: Boolean(me?.can_register_apps),
    };
}
