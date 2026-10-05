// AppStore page listing deployments (/appstore/deployments), linking to
// deployment-detail.jsx.
import { useMemo, useState } from 'react';
import { Alert, Anchor, Badge, Container, Group, SegmentedControl, Stack, Table, Text, Title } from '@mantine/core';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Link } from 'wouter';
import { useAppStoreApi } from '/appstore/api-appstore.jsx';
import { appstoreKeys } from '/appstore/query-keys.js';
import { IN_FLIGHT, StatusBadge } from '/appstore/status.jsx';
import { useMe } from '/appstore/use-appstore.jsx';
import { LoadError, Loading } from '/helper/query-state.jsx';
import { formatDateTime } from '/format-date.js';

/**
 * The deployments the caller owns, is a team member of, or shares an
 * OpenStack project with (E2), newest first, with a busy/settled filter.
 * While any of them is busy, the list refreshes itself (every 3 s). App names
 * come from the app list, since a deployment carries only its appId.
 */
export function Deployments() {
    const { t } = useTranslation();
    const api = useAppStoreApi();
    const { me } = useMe();
    const [filter, setFilter] = useState('all');
    const apps = useQuery({ queryKey: appstoreKeys.apps(), queryFn: api.listApps });
    const query = useQuery({
        queryKey: appstoreKeys.deployments(),
        queryFn: api.listDeployments,
        refetchInterval: (q) => (q.state.data?.some(d => IN_FLIGHT.has(d.status)) ? 3000 : false),
    });
    const appName = useMemo(() => Object.fromEntries((apps.data ?? []).map(a => [a.appId, a.name])), [apps.data]);
    const mine = (d) => me && d.userId && d.userId === me.userId;
    const rows = (query.data ?? [])
        .filter(d => filter === 'all' || (filter === 'busy' ? IN_FLIGHT.has(d.status) : !IN_FLIGHT.has(d.status)))
        .sort((a, b) => String(b.created_at ?? '').localeCompare(String(a.created_at ?? '')));

    return (
        <Container size="xl" py="xl">
            <Stack gap="md">
                <Group justify="space-between">
                    <Title order={2}>{t('appstore.deployments.title')}</Title>
                    <SegmentedControl value={filter} onChange={setFilter} data={[
                        { value: 'all', label: t('appstore.deployments.filterAll') },
                        { value: 'busy', label: t('appstore.deployments.filterBusy') },
                        { value: 'settled', label: t('appstore.deployments.filterSettled') },
                    ]} />
                </Group>
                {query.isPending && <Loading />}
                {query.isError && <LoadError query={query} />}
                {query.isSuccess && rows.length === 0 && <Alert color="gray">{t('appstore.deployments.empty')}</Alert>}
                {rows.length > 0 && (
                    <Table striped highlightOnHover withTableBorder>
                        <Table.Thead>
                            <Table.Tr>
                                <Table.Th>{t('appstore.deployments.name')}</Table.Th>
                                <Table.Th>{t('appstore.deployments.app')}</Table.Th>
                                <Table.Th>{t('appstore.deployments.course')}</Table.Th>
                                <Table.Th>{t('appstore.deployments.status')}</Table.Th>
                                <Table.Th>{t('appstore.deployments.created')}</Table.Th>
                            </Table.Tr>
                        </Table.Thead>
                        <Table.Tbody>
                            {rows.map(d => (
                                <Table.Tr key={d.deploymentId}>
                                    <Table.Td>
                                        <Group gap="xs">
                                            <Anchor component={Link} href={`/deployments/${d.deploymentId}`}>{d.name}</Anchor>
                                            {mine(d) && <Badge size="xs" variant="outline">{t('appstore.deployments.mine')}</Badge>}
                                        </Group>
                                    </Table.Td>
                                    <Table.Td><Text size="sm">{appName[d.appId] ?? '—'} <Text span c="dimmed" size="xs">{d.releaseTag}</Text></Text></Table.Td>
                                    <Table.Td><Text size="sm">{String(d.course ?? '').replace(/^group:/, '')}</Text></Table.Td>
                                    <Table.Td><StatusBadge status={d.status} /></Table.Td>
                                    <Table.Td><Text size="sm">{d.created_at ? formatDateTime(d.created_at) : '—'}</Text></Table.Td>
                                </Table.Tr>
                            ))}
                        </Table.Tbody>
                    </Table>
                )}
            </Stack>
        </Container>
    );
}
