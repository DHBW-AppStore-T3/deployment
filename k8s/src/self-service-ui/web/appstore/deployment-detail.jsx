// AppStore page for one deployment (/appstore/deployments/:deploymentId):
// status, live progress, actions, and tabs for overview, teams/access,
// resources and task logs.
import { useEffect, useRef, useState } from 'react';
import { Alert, Anchor, Badge, Button, Card, Code, Container, Group, Progress, ScrollArea, Stack, Table, Tabs, Text, Title, Tooltip } from '@mantine/core';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowLeft, Ban, Mail, Pause, Play, RefreshCw, RotateCcw, Trash2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Link, useLocation } from 'wouter';
import { useAppStoreApi } from '/appstore/api-appstore.jsx';
import { appstoreKeys } from '/appstore/query-keys.js';
import { AccessView } from '/appstore/access-view.jsx';
import { allowedActions, IN_FLIGHT, StatusBadge } from '/appstore/status.jsx';
import { useDeploymentStream } from '/appstore/use-deployment-stream.jsx';
import { logLine, parseTaskLogs } from '/appstore/task-logs.js';
import { ExternalLink } from '/helper/external-link.jsx';
import { LoadError, Loading, useApiMutation } from '/helper/query-state.jsx';
import { useConfirm } from '/providers/confirm.jsx';
import { formatDateTime } from '/format-date.js';

/**
 * One deployment. What is shown follows `permissions` from the API: the owner
 * view (owner, project peers, admins) sees tasks, logs, all teams and the
 * outputs (sensitive ones redacted); team members see their own team and their
 * own access. Actions — pause, resume, destroy — are for those who may operate
 * it, and run with their own OpenStack credential (E2).
 *
 * The route is /appstore/deployments/<id>, which the owner's mail links to.
 */
export function DeploymentDetail({ params }) {
    const { t } = useTranslation();
    const api = useAppStoreApi();
    const queryClient = useQueryClient();
    const id = params.deploymentId;

    const query = useQuery({
        queryKey: appstoreKeys.deployment(id),
        queryFn: () => api.getDeployment(id),
        // Belt and braces next to the live stream: a status change the stream
        // did not deliver (a proxy dropped it) still shows up.
        refetchInterval: (q) => (IN_FLIGHT.has(q.state.data?.status) ? 5000 : false),
    });
    const dep = query.data;
    const busy = IN_FLIGHT.has(dep?.status);
    const stream = useDeploymentStream(id, { enabled: busy });

    // When the running task ends, everything about the deployment may have
    // changed: status, outputs, resources, access.
    useEffect(() => {
        if (stream.ended) queryClient.invalidateQueries({ queryKey: appstoreKeys.deployment(id) });
    }, [stream.ended, id, queryClient]);

    if (query.isPending) return <Container py="xl"><Loading /></Container>;
    if (query.isError) return <Container py="xl"><LoadError query={query} /></Container>;

    const perms = dep.permissions ?? { owner_view: false, operate: false };
    // The list answer lags the stream by up to a refetch: once the worker has
    // reported a phase, a queued deployment is running.
    const shownStatus = dep.status === 'pending' && stream.phase ? 'running' : dep.status;

    return (
        <Container size="xl" py="xl">
            <Stack gap="md">
                <Anchor component={Link} href="/deployments" size="sm"><Group gap={4}><ArrowLeft size={14} />{t('appstore.detail.back')}</Group></Anchor>
                <Group justify="space-between" align="flex-start">
                    <Stack gap={4}>
                        <Group gap="sm"><Title order={2}>{dep.name}</Title><StatusBadge status={shownStatus} /></Group>
                        <Text size="sm" c="dimmed">
                            {/* The catalogue entry of a private app is the owner's; members would land on an error page. */}
                            {perms.owner_view ? <Anchor component={Link} href={`/apps/${dep.appId}`}>{dep.app?.name}</Anchor> : dep.app?.name}
                            {' · '}{dep.releaseTag} <Code>{String(dep.commit_sha ?? '').slice(0, 8)}</Code>
                            {' · '}{String(dep.course ?? '').replace(/^group:/, '')}
                        </Text>
                        <Text size="xs" c="dimmed">
                            {dep.runtime === 'kubernetes'
                                ? t('appstore.detail.ownerAndPods', { owner: dep.user?.email ?? '' })
                                : t('appstore.detail.ownerAndProject', { owner: dep.user?.email ?? '', project: dep.os_project_id ?? '' })}
                        </Text>
                    </Stack>
                    {perms.operate && <Actions deployment={dep} />}
                </Group>

                {busy && <LiveProgress stream={stream} latest={dep.latest_task} />}
                {dep.status === 'destroyed' && (
                    <Alert color="gray" title={t('appstore.detail.destroyedTitle')}>
                        {t('appstore.detail.destroyedMessage')} <Anchor component={Link} href="/deployments">{t('appstore.detail.back')}</Anchor>
                    </Alert>
                )}
                {!busy && dep.latest_task?.status === 'failed' && (
                    <Alert color="red" title={t('appstore.detail.failedTitle')}>{t('appstore.detail.failedMessage')}</Alert>
                )}

                <Tabs defaultValue={perms.owner_view ? 'overview' : 'access'} keepMounted={false}>
                    <Tabs.List>
                        {perms.owner_view && <Tabs.Tab value="overview">{t('appstore.detail.tabOverview')}</Tabs.Tab>}
                        <Tabs.Tab value="access">{perms.owner_view ? t('appstore.detail.tabTeams') : t('appstore.detail.tabMyAccess')}</Tabs.Tab>
                        {perms.owner_view && <Tabs.Tab value="resources">{t('appstore.detail.tabResources')}</Tabs.Tab>}
                        {perms.owner_view && <Tabs.Tab value="log">{t('appstore.detail.tabLog')}</Tabs.Tab>}
                    </Tabs.List>
                    {perms.owner_view && <Tabs.Panel value="overview" pt="md"><Overview deployment={dep} /></Tabs.Panel>}
                    <Tabs.Panel value="access" pt="md">
                        {perms.owner_view ? <TeamsPanel deployment={dep} /> : <MyAccessPanel deployment={dep} />}
                    </Tabs.Panel>
                    {perms.owner_view && <Tabs.Panel value="resources" pt="md"><Resources deployment={dep} operate={perms.operate} /></Tabs.Panel>}
                    {perms.owner_view && <Tabs.Panel value="log" pt="md"><TaskLog deployment={dep} /></Tabs.Panel>}
                </Tabs>
            </Stack>
        </Container>
    );
}

/**
 * Pause, resume and destroy/delete buttons, offered per allowedActions(status).
 * Both destroy and delete call DELETE; the API either starts a destroy task
 * (the view then follows it) or removes a deployment with nothing to tear down.
 */
function Actions({ deployment: dep }) {
    const { t } = useTranslation();
    const api = useAppStoreApi();
    const confirm = useConfirm();
    const [, navigate] = useLocation();
    const allowed = allowedActions(dep.status);
    const invalidates = [appstoreKeys.deployment(dep.deploymentId), appstoreKeys.deployments()];
    const pause = useApiMutation({ mutationFn: () => api.pauseDeployment(dep.deploymentId), invalidates });
    const resume = useApiMutation({ mutationFn: () => api.resumeDeployment(dep.deploymentId), invalidates });
    const remove = useApiMutation({
        mutationFn: () => api.deleteDeployment(dep.deploymentId),
        invalidates,
        // A cancelled or failed-before-anything deployment is removed at once
        // (204, no body); otherwise a destroy task starts and the view follows it.
        onSuccess: (res) => { if (!res?.task_id) navigate('/deployments'); },
    });
    const destroys = allowed.has('destroy');
    // A pod deployment can be called off while it is still being set up; the API removes what it created.
    const cancel = useApiMutation({ mutationFn: () => api.cancelDeployment(dep.deploymentId), invalidates });
    const cancellable = dep.runtime === 'kubernetes' && ['pending', 'running'].includes(dep.status);

    return (
        <Group gap="xs">
            {cancellable && (
                <Button color="red" variant="light" leftSection={<Ban size={16} />} loading={cancel.isPending}
                    onClick={async () => {
                        if (await confirm({ title: t('appstore.detail.cancelTitle'), message: t('appstore.detail.cancelMessage', { name: dep.name }), confirmLabel: t('appstore.detail.cancel') })) cancel.mutate();
                    }}>
                    {t('appstore.detail.cancel')}
                </Button>
            )}
            {allowed.has('pause') && (
                <Button variant="default" leftSection={<Pause size={16} />} loading={pause.isPending} onClick={() => pause.mutate()}>
                    {t('appstore.detail.pause')}
                </Button>
            )}
            {allowed.has('resume') && (
                <Button variant="default" leftSection={<Play size={16} />} loading={resume.isPending} onClick={() => resume.mutate()}>
                    {t('appstore.detail.resume')}
                </Button>
            )}
            {(destroys || allowed.has('delete')) && (
                <Button color="red" variant="light" leftSection={<Trash2 size={16} />} loading={remove.isPending}
                    onClick={async () => {
                        if (await confirm({
                            title: destroys ? t('appstore.detail.destroyTitle') : t('appstore.detail.deleteTitle'),
                            message: destroys ? t(dep.runtime === 'kubernetes' ? 'appstore.detail.destroyMessagePods' : 'appstore.detail.destroyMessage', { name: dep.name }) : t('appstore.detail.deleteMessage', { name: dep.name }),
                            confirmLabel: destroys ? t('appstore.detail.destroy') : t('appstore.detail.delete'),
                        })) remove.mutate();
                    }}>
                    {destroys ? t('appstore.detail.destroy') : t('appstore.detail.delete')}
                </Button>
            )}
        </Group>
    );
}

/**
 * Progress bar, phase and the last log lines of the running task, from the live
 * stream, falling back to the latest task's fields until the stream has spoken.
 */
function LiveProgress({ stream, latest }) {
    const { t } = useTranslation();
    const viewport = useRef(null);
    const pct = stream.progress ?? latest?.progress_pct ?? 0;
    const phase = stream.phase ?? latest?.current_phase;
    // Follow the newest line.
    useEffect(() => {
        if (viewport.current) viewport.current.scrollTop = viewport.current.scrollHeight;
    }, [stream.logs.length]);

    return (
        <Card withBorder>
            <Stack gap="xs">
                <Group justify="space-between">
                    <Text fw={500}>
                        {phase ? t('appstore.detail.phase', { phase: phaseLabel(phase), index: stream.phaseIndex ?? '?', total: stream.totalPhases ?? '?' }) : t('appstore.detail.waiting')}
                    </Text>
                    <Badge variant="dot" color={stream.connection === 'live' ? 'green' : 'gray'}>{t(`appstore.detail.connection.${stream.connection ?? 'idle'}`)}</Badge>
                </Group>
                <Progress value={pct} animated striped />
                <ScrollArea h={220} viewportRef={viewport} type="auto">
                    <Code block style={{ whiteSpace: 'pre-wrap', minHeight: 200 }}>
                        {stream.logs.length ? stream.logs.map(logLine).join('\n') : t('appstore.detail.noLogYet')}
                    </Code>
                </ScrollArea>
            </Stack>
        </Card>
    );
}

/** A worker phase id as a readable label: PACKER_BUILD:web -> "Packer build (web)". */
function phaseLabel(phase) {
    const [name, key] = String(phase).split(':');
    const words = name.toLowerCase().split('_').join(' ');
    const label = words.charAt(0).toUpperCase() + words.slice(1);
    return key ? `${label} (${key})` : label;
}

/** Owner-view tab: creation date, latest task and the outputs (redacted ones hidden). */
function Overview({ deployment: dep }) {
    const { t } = useTranslation();
    const outputs = dep.outputs?.raw ?? null;
    return (
        <Stack gap="md">
            <Table variant="vertical" withTableBorder>
                <Table.Tbody>
                    <Table.Tr><Table.Th w={220}>{t('appstore.detail.created')}</Table.Th><Table.Td>{dep.created_at ? formatDateTime(dep.created_at) : '—'}</Table.Td></Table.Tr>
                    <Table.Tr><Table.Th>{t('appstore.detail.lastTask')}</Table.Th><Table.Td>{dep.latest_task ? `${t(`appstore.taskType.${dep.latest_task.type}`, { defaultValue: dep.latest_task.type })} · ${t(`appstore.taskStatus.${dep.latest_task.status}`, { defaultValue: dep.latest_task.status })}` : '—'}</Table.Td></Table.Tr>
                </Table.Tbody>
            </Table>
            <Title order={5}>{t('appstore.detail.outputs')}</Title>
            {!outputs ? <Text size="sm" c="dimmed">{t('appstore.detail.noOutputs')}</Text> : (
                <Table withTableBorder>
                    <Table.Tbody>
                        {Object.entries(outputs).map(([name, o]) => (
                            <Table.Tr key={name}>
                                <Table.Th w={220}><Code>{name}</Code></Table.Th>
                                <Table.Td>
                                    {o?.redacted
                                        ? <Text size="sm" c="dimmed">{t('appstore.detail.redacted')}</Text>
                                        : <Code block style={{ whiteSpace: 'pre-wrap' }}>{JSON.stringify(o?.value ?? o, null, 2)}</Code>}
                                </Table.Td>
                            </Table.Tr>
                        ))}
                    </Table.Tbody>
                </Table>
            )}
        </Stack>
    );
}

/** Owner-view tab: every team with its members and a per-member "resend access mail" button (only after a successful deploy). */
function TeamsPanel({ deployment: dep }) {
    const { t } = useTranslation();
    const api = useAppStoreApi();
    const resend = useApiMutation({ mutationFn: ({ teamId, userId }) => api.resendAccess(dep.deploymentId, teamId, userId) });
    const [sent, setSent] = useState(null);
    const teams = dep.teams ?? [];
    if (!teams.length) return <Text size="sm" c="dimmed">{t('appstore.detail.noTeams')}</Text>;
    return (
        <Stack gap="md">
            <Text size="sm" c="dimmed">{t('appstore.detail.teamsIntro')}</Text>
            {teams.map(team => (
                <Card key={team.teamId} withBorder>
                    <Title order={5} mb="xs">{team.name}</Title>
                    {team.members?.length ? (
                        <Table>
                            <Table.Tbody>
                                {team.members.map(m => (
                                    <Table.Tr key={m.userId}>
                                        <Table.Td>{m.email}</Table.Td>
                                        <Table.Td w={220} ta="right">
                                            <Tooltip label={t('appstore.detail.resendHint')}>
                                                <Button size="xs" variant="subtle" leftSection={<Mail size={14} />}
                                                    disabled={dep.status !== 'success'}
                                                    loading={resend.isPending && resend.variables?.userId === m.userId}
                                                    onClick={() => resend.mutate({ teamId: team.teamId, userId: m.userId }, { onSuccess: () => setSent(m.email) })}>
                                                    {sent === m.email ? t('appstore.detail.resent') : t('appstore.detail.resend')}
                                                </Button>
                                            </Tooltip>
                                        </Table.Td>
                                    </Table.Tr>
                                ))}
                            </Table.Tbody>
                        </Table>
                    ) : <Text size="sm" c="dimmed">{t('appstore.detail.emptyTeam')}</Text>}
                </Card>
            ))}
        </Stack>
    );
}

/** Team-member tab: the caller's own team and access (api.getMyDeploymentAccess). */
function MyAccessPanel({ deployment: dep }) {
    const { t } = useTranslation();
    const api = useAppStoreApi();
    const query = useQuery({ queryKey: appstoreKeys.myDeploymentAccess(dep.deploymentId), queryFn: () => api.getMyDeploymentAccess(dep.deploymentId) });
    return (
        <Stack gap="sm">
            {/* The member view lists only the caller's own team (one per person). */}
            {dep.teams?.[0] && <Text size="sm">{t('appstore.detail.yourTeam', { team: dep.teams[0].name })}</Text>}
            {query.isPending && <Loading />}
            {query.isError && <LoadError query={query} />}
            {query.isSuccess && <AccessView userAccounts={query.data.user_accounts} teamVms={query.data.team_vms} />}
        </Stack>
    );
}

/**
 * Owner-view tab: the deployment's OpenStack resources (api.listResourcesOf,
 * refreshed from OpenStack), with "redeploy" for instances if the caller may
 * operate and the deployment succeeded.
 */
// Statuses in which the API accepts a single-VM redeploy (services/lifecycle.py).
const REDEPLOYABLE = new Set(['success', 'redeploy_failed']);

function Resources({ deployment: dep, operate }) {
    if (dep.runtime === 'kubernetes') return <PodWorkloads deployment={dep} operate={operate} />;
    return <VmResources deployment={dep} operate={operate} />;
}

/**
 * Owner-view tab for a deployment that runs as pods: one row per team's or
 * person's workload with its state, link and last warning, and restart / reset
 * (api.redeployResource: the workload name, `reset:<name>` also drops its data).
 */
function PodWorkloads({ deployment: dep, operate }) {
    const { t } = useTranslation();
    const api = useAppStoreApi();
    const confirm = useConfirm();
    const query = useQuery({
        queryKey: appstoreKeys.deploymentResources(dep.deploymentId),
        queryFn: () => api.listResourcesOf(dep.deploymentId, true),
        refetchInterval: 10_000,
    });
    const act = useApiMutation({
        mutationFn: (address) => api.redeployResource(dep.deploymentId, address),
        invalidates: [appstoreKeys.deployment(dep.deploymentId), appstoreKeys.deployments()],
    });
    const rows = query.data?.workloads ?? [];
    const canAct = operate && REDEPLOYABLE.has(dep.status);
    return (
        <Stack gap="sm">
            <Group justify="space-between">
                <Text size="sm" c="dimmed">{t('appstore.detail.podsIntro')}</Text>
                <Button size="xs" variant="default" leftSection={<RefreshCw size={14} />} loading={query.isFetching} onClick={() => query.refetch()}>
                    {t('appstore.detail.refresh')}
                </Button>
            </Group>
            {query.isPending && <Loading />}
            {query.isError && <LoadError query={query} />}
            {query.isSuccess && query.data.live === false && <Alert color="yellow">{t('appstore.detail.podsNotLive')}</Alert>}
            {query.isSuccess && rows.length === 0 && <Text size="sm" c="dimmed">{t('appstore.detail.noWorkloads')}</Text>}
            {rows.length > 0 && (
                <Table withTableBorder striped>
                    <Table.Thead>
                        <Table.Tr>
                            <Table.Th>{t('appstore.detail.workload')}</Table.Th>
                            <Table.Th>{t('appstore.detail.team')}</Table.Th>
                            <Table.Th>{t('appstore.detail.state')}</Table.Th>
                            <Table.Th>{t('appstore.detail.restarts')}</Table.Th>
                            <Table.Th>{t('appstore.access.url')}</Table.Th>
                            <Table.Th />
                        </Table.Tr>
                    </Table.Thead>
                    <Table.Tbody>
                        {rows.map(w => (
                            <Table.Tr key={w.workload}>
                                <Table.Td><Text size="sm" fw={500}>{w.user ?? w.workload}</Text>{w.lastEvent && <Text size="xs" c="orange">{w.lastEvent}</Text>}</Table.Td>
                                <Table.Td>{w.team ?? '—'}</Table.Td>
                                <Table.Td><Badge variant="light" color={w.ready ? 'green' : w.phase === 'Stopped' ? 'yellow' : 'orange'}>{w.phase}</Badge></Table.Td>
                                <Table.Td>{w.restarts}</Table.Td>
                                <Table.Td>{w.url ? <ExternalLink href={w.url}>{w.url.replace(/^https:\/\//, '')}</ExternalLink> : '—'}</Table.Td>
                                <Table.Td ta="right">
                                    {canAct && (
                                        <Group gap={4} justify="flex-end" wrap="nowrap">
                                            <Button size="xs" variant="subtle" leftSection={<RotateCcw size={14} />} loading={act.isPending && act.variables === w.workload}
                                                onClick={async () => {
                                                    if (await confirm({ title: t('appstore.detail.restartTitle'), message: t('appstore.detail.restartMessage', { name: w.workload }), confirmLabel: t('appstore.detail.restart') })) act.mutate(w.workload);
                                                }}>
                                                {t('appstore.detail.restart')}
                                            </Button>
                                            <Button size="xs" variant="subtle" color="red" loading={act.isPending && act.variables === `reset:${w.workload}`}
                                                onClick={async () => {
                                                    if (await confirm({ title: t('appstore.detail.resetTitle'), message: t('appstore.detail.resetMessage', { name: w.workload }), confirmLabel: t('appstore.detail.reset') })) act.mutate(`reset:${w.workload}`);
                                                }}>
                                                {t('appstore.detail.reset')}
                                            </Button>
                                        </Group>
                                    )}
                                </Table.Td>
                            </Table.Tr>
                        ))}
                    </Table.Tbody>
                </Table>
            )}
        </Stack>
    );
}

function VmResources({ deployment: dep, operate }) {
    const { t } = useTranslation();
    const api = useAppStoreApi();
    const confirm = useConfirm();
    const query = useQuery({
        queryKey: appstoreKeys.deploymentResources(dep.deploymentId),
        queryFn: () => api.listResourcesOf(dep.deploymentId, true),
    });
    const redeploy = useApiMutation({
        mutationFn: (address) => api.redeployResource(dep.deploymentId, address),
        invalidates: [appstoreKeys.deployment(dep.deploymentId), appstoreKeys.deployments()],
    });
    const rows = query.data?.resources ?? [];
    return (
        <Stack gap="sm">
            <Group justify="space-between">
                <Text size="sm" c="dimmed">{t('appstore.detail.resourcesIntro')}</Text>
                <Button size="xs" variant="default" leftSection={<RefreshCw size={14} />} loading={query.isFetching} onClick={() => query.refetch()}>
                    {t('appstore.detail.refresh')}
                </Button>
            </Group>
            {query.isPending && <Loading />}
            {query.isError && <LoadError query={query} />}
            {query.isSuccess && rows.length === 0 && <Text size="sm" c="dimmed">{t('appstore.detail.noResources')}</Text>}
            {rows.length > 0 && (
                <Table withTableBorder striped>
                    <Table.Thead>
                        <Table.Tr>
                            <Table.Th>{t('appstore.detail.resource')}</Table.Th>
                            <Table.Th>{t('appstore.detail.team')}</Table.Th>
                            <Table.Th>{t('appstore.detail.state')}</Table.Th>
                            <Table.Th>{t('appstore.detail.addresses')}</Table.Th>
                            <Table.Th />
                        </Table.Tr>
                    </Table.Thead>
                    <Table.Tbody>
                        {rows.map(r => (
                            <Table.Tr key={r.address}>
                                <Table.Td><Text size="sm" fw={500}>{r.display_name}</Text><Text size="xs" c="dimmed">{r.type}</Text></Table.Td>
                                <Table.Td>{r.team ?? '—'}</Table.Td>
                                <Table.Td>{r.lifecycle ? <Badge variant="light" color={r.lifecycle.status === 'ACTIVE' ? 'green' : 'gray'}>{r.lifecycle.status}</Badge> : '—'}</Table.Td>
                                <Table.Td><Text size="xs">{(r.addresses ?? []).flatMap(a => [a.fixed_ip, a.floating_ip]).filter(Boolean).join(', ') || '—'}</Text></Table.Td>
                                <Table.Td ta="right">
                                    {operate && r.category === 'instance' && REDEPLOYABLE.has(dep.status) && (
                                        <Button size="xs" variant="subtle" leftSection={<RotateCcw size={14} />} loading={redeploy.isPending && redeploy.variables === r.address}
                                            onClick={async () => {
                                                if (await confirm({ title: t('appstore.detail.redeployTitle'), message: t('appstore.detail.redeployMessage', { name: r.display_name }), confirmLabel: t('appstore.detail.redeploy') })) redeploy.mutate(r.address);
                                            }}>
                                            {t('appstore.detail.redeploy')}
                                        </Button>
                                    )}
                                </Table.Td>
                            </Table.Tr>
                        ))}
                    </Table.Tbody>
                </Table>
            )}
        </Stack>
    );
}

/** Owner-view tab: the deployment's tasks, newest first, and the stored log of the selected one. */
function TaskLog({ deployment: dep }) {
    const { t } = useTranslation();
    const api = useAppStoreApi();
    const tasks = useQuery({ queryKey: appstoreKeys.deploymentTasks(dep.deploymentId), queryFn: () => api.listTasks(dep.deploymentId) });
    const [open, setOpen] = useState(null);
    const list = [...(tasks.data ?? [])].sort((a, b) => String(b.created_at).localeCompare(String(a.created_at)));
    const shown = list.find(x => x.taskId === open) ?? list[0];
    const { entries, tail } = parseTaskLogs(shown?.logs);

    if (tasks.isPending) return <Loading />;
    if (tasks.isError) return <LoadError query={tasks} />;
    if (!list.length) return <Text size="sm" c="dimmed">{t('appstore.detail.noTasks')}</Text>;
    return (
        <Stack gap="sm">
            <Table withTableBorder highlightOnHover>
                <Table.Tbody>
                    {list.map(task => (
                        <Table.Tr key={task.taskId} onClick={() => setOpen(task.taskId)} style={{ cursor: 'pointer' }}
                            bg={task.taskId === shown?.taskId ? 'var(--mantine-color-gray-1)' : undefined}>
                            <Table.Td>{t(`appstore.taskType.${task.type}`, { defaultValue: task.type })}</Table.Td>
                            <Table.Td>{t(`appstore.taskStatus.${task.status}`, { defaultValue: task.status })}</Table.Td>
                            <Table.Td>{formatDateTime(task.created_at)}</Table.Td>
                            <Table.Td>{task.finished_at ? formatDateTime(task.finished_at) : '—'}</Table.Td>
                        </Table.Tr>
                    ))}
                </Table.Tbody>
            </Table>
            <ScrollArea h={360} type="auto">
                <Code block style={{ whiteSpace: 'pre-wrap' }}>
                    {[...entries.map(logLine), tail].filter(Boolean).join('\n') || t('appstore.detail.noLog')}
                </Code>
            </ScrollArea>
        </Stack>
    );
}
