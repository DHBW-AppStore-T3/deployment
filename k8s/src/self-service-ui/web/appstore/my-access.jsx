// AppStore page "Meine Zugänge" (/appstore/my-access): the signed-in
// person's own access to every deployment they are a team member of.
import { Alert, Anchor, Badge, Card, Container, Group, Stack, Text, Title } from '@mantine/core';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Link } from 'wouter';
import { useAppStoreApi } from '/appstore/api-appstore.jsx';
import { appstoreKeys } from '/appstore/query-keys.js';
import { AccessView } from '/appstore/access-view.jsx';
import { StatusBadge } from '/appstore/status.jsx';
import { LoadError, Loading } from '/helper/query-state.jsx';

/**
 * "Meine Zugänge": every environment the signed-in person is a team member
 * of, with their own access (api.listMyAccess), shown once the deployment is
 * up (success or paused). The mails only point here (plan E5). The route is
 * /appstore/my-access, which the API's mails link to — keep them in step.
 */
export function MyAccess() {
    const { t } = useTranslation();
    const api = useAppStoreApi();
    const query = useQuery({ queryKey: appstoreKeys.myAccess(), queryFn: api.listMyAccess });

    return (
        <Container size="lg" py="xl">
            <Stack gap="md">
                <Title order={2}>{t('appstore.myAccess.title')}</Title>
                <Text size="sm" c="dimmed">{t('appstore.myAccess.intro')}</Text>

                {query.isPending && <Loading />}
                {query.isError && <LoadError query={query} />}
                {query.isSuccess && query.data.length === 0 && (
                    <Alert color="gray" title={t('appstore.myAccess.emptyTitle')}>{t('appstore.myAccess.emptyMessage')}</Alert>
                )}
                {query.data?.map(entry => (
                    <Card key={entry.deploymentId} withBorder padding="lg">
                        <Stack gap="sm">
                            <Group justify="space-between">
                                <Stack gap={0}>
                                    <Title order={4}>{entry.name}</Title>
                                    <Text size="sm" c="dimmed">
                                        {t('appstore.myAccess.appAndTeam', { app: entry.app_name, team: entry.team_name })}
                                    </Text>
                                </Stack>
                                <Group gap="xs">
                                    <Badge variant="outline">{entry.course.replace(/^group:/, '')}</Badge>
                                    <StatusBadge status={entry.status} />
                                </Group>
                            </Group>
                            {entry.status === 'success' || entry.status === 'paused'
                                ? <AccessView userAccounts={entry.user_accounts} teamVms={entry.team_vms} />
                                : <Text size="sm" c="dimmed">{t('appstore.myAccess.notReady')}</Text>}
                            <Anchor component={Link} href={`/deployments/${entry.deploymentId}`} size="xs">{t('appstore.myAccess.details')}</Anchor>
                        </Stack>
                    </Card>
                ))}
            </Stack>
        </Container>
    );
}
