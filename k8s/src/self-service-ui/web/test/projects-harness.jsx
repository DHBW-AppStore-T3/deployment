import { ProjectConfigContext } from '/projects/projects.jsx';
import { renderWithProviders } from '/test/render-harness.jsx';

// The Cloud Projects part of the render harness: the section's config
// context and the fixtures its views are tested against. Kept apart from
// render-harness.jsx so other areas do not load the projects section to
// render a view of their own.

const CONFIG = {
    resources: [
        { id: 'cores', name: 'Cores', default: 4, min: 1, max: 64 },
        { id: 'ram', name: 'RAM', unit: 'GB', default: 8, min: 1, max: 256 },
    ],
    openstackRoles: ['member', 'reader'],
    dummyDevUsers: [],
};

export function renderView(ui, { config = CONFIG, user } = {}) {
    return renderWithProviders(
        <ProjectConfigContext.Provider value={config}>{ui}</ProjectConfigContext.Provider>,
        user ? { user } : undefined,
    );
}

// A budget tree deep enough to exercise the parts that broke: a root with
// children, a branch below it, and a leaf carrying the dates and the measured
// usage that the cards format.
export function fixtureTree() {
    const budget = (id, parentId, name, childCount) => ({
        id, parent_id: parentId, kind: 'budget', status: 'approved', name,
        child_count: childCount, limit: { cores: 32, ram: 128 },
        admin_scope: ['user:dennis.pfisterer@dhbw.de'],
        usage: { approved: { limit: { cores: 8, ram: 16 }, node_ids: [] } },
        created_at: '2026-08-01T10:00:00Z',
    });
    const project = (id, parentId, name, extra = {}) => ({
        id, parent_id: parentId, kind: 'project', status: 'approved', name,
        child_count: 0, limit: { cores: 4, ram: 8 }, os_in_use: { cores: 2, ram: 4 },
        owner: 'user:dennis.pfisterer@dhbw.de', os_project_id: 'os-1',
        created_at: '2026-08-02T10:00:00Z',
        termination_date: '2027-03-31',
        authorized_users: [{ token: 'user:someone@dhbw.de', openstack_role: 'member' }],
        history: [{ timestamp: '2026-08-02T10:00:00Z', event: 'created', actor: 'dennis.pfisterer@dhbw.de', status_to: 'pending' }],
        ...extra,
    });

    // A project with a change waiting, so the diff block renders too. Without
    // one, whole branches of the cards are never reached — that is not a
    // hypothetical: the missing-import release only broke inside them, and a
    // fixture of plain approved projects would have gone green on it.
    const changing = project('p_2', 'b_ma', 'Projekt mit Änderung', {
        status: 'change_pending',
        pending: {
            limit: { cores: 8, ram: 16 },
            termination_date: '2027-09-30',
            authorized_users: [
                { token: 'user:someone@dhbw.de', openstack_role: 'reader' },
                { token: 'user:neu@dhbw.de', openstack_role: 'member' },
            ],
        },
    });

    return {
        roots: [budget('b_root', null, 'Organization Root', 1)],
        children: {
            b_root: { items: [budget('b_ma', 'b_root', 'Mannheim', 2)], total: 2 },
            b_ma: { items: [project('p_1', 'b_ma', 'Mein Projekt'), changing], total: 2 },
        },
    };
}

// The staging shape from 2026-08-25: the caller manages the root and a budget
// two levels below it, but NOT the faculty budget in between. my-budgets hands
// back the two managed ones and nothing else, so the view has to decide from the
// ancestor chain alone which of them belongs at the top.
//
// `managed` is what my-budgets answers; `children` is what expanding returns,
// and it contains the in-between node the caller cannot see in their own list.
export function fixtureSkippedLevel() {
    const budget = (id, parentId, name, childCount, ancestors) => ({
        id, parent_id: parentId, kind: 'budget', status: 'approved', name,
        child_count: childCount, limit: { cores: 32, ram: 128 },
        ancestor_ids: ancestors,
        admin_scope: ['user:dennis.pfisterer@dhbw.de'],
        usage: { approved: { limit: { cores: 8, ram: 16 }, node_ids: [] } },
        created_at: '2026-08-01T10:00:00Z',
    });

    const root = budget('b_root', null, 'Organization Root', 1, []);
    const mannheim = budget('b_ma', 'b_root', 'Mannheim', 1, ['b_root']);
    const wi = budget('b_wi', 'b_ma', 'WI-Budget', 0, ['b_root', 'b_ma']);

    return {
        // Mannheim is deliberately absent: it belongs to someone else.
        roots: [root, wi],
        children: {
            b_root: { items: [mannheim], total: 1 },
            b_ma: { items: [wi], total: 1 },
        },
    };
}

// The api-nodes facade, answering from a fixture. Every method the views call
// has to exist here: a missing one shows up as "not a function" during render,
// which is the failure mode this harness is for.
export function fakeNodesApi(tree = fixtureTree()) {
    const page = (items) => ({ items, total: items.length });
    const all = [...tree.roots, ...Object.values(tree.children).flatMap(p => p.items)];
    const byId = Object.fromEntries(all.map(n => [n.id, n]));

    return {
        getConfig: async () => CONFIG,
        getNode: async (id) => byId[id] ?? null,
        listChildren: async (id) => tree.children[id] ?? { items: [], total: 0 },
        searchNodes: async () => page([]),
        listMine: async () => page(all.filter(n => n.kind === 'project')),
        listMyBudgets: async () => page(tree.roots),
        listEligibleForMe: async () => page([]),
        listEligibleForOwner: async () => page([]),
        listToManage: async () => page([]),
        countToManage: async () => 0,
        countMyBudgets: async () => tree.roots.length,
        countEligible: async () => 0,
        searchIdentities: async () => [],
        searchPrincipalDetails: async () => [],
        searchPrincipals: async () => [],
        getRoleSwitch: async () => null,
        setRoleSwitch: async () => null,
        clearRoleSwitch: async () => null,
        getReconcilerStatus: async () => ({ enabled: false }),
        listApiTokens: async () => [],
        createApiToken: async () => ({}),
        deleteApiToken: async () => ({}),
        create: async () => ({}),
        update: async () => ({}),
        requestChange: async () => ({}),
        approve: async () => ({}),
        reject: async () => ({}),
        release: async () => ({}),
        move: async () => ({}),
        transferOwner: async () => ({}),
        promote: async () => ({}),
        deleteNode: async () => ({}),
    };
}
