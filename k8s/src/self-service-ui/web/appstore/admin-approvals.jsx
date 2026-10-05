// AppStore admin page (/appstore/admin): pending app version approvals.
import { useState } from 'react';
import { Alert, Anchor, Button, Card, Code, Container, Group, Modal, Stack, Text, Textarea, Title } from '@mantine/core';
import { useQuery } from '@tanstack/react-query';
import { Check, X } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Link } from 'wouter';
import { useAppStoreApi } from '/appstore/api-appstore.jsx';
import { appstoreKeys } from '/appstore/query-keys.js';
import { useMe } from '/appstore/use-appstore.jsx';
import { LoadError, Loading, useApiMutation } from '/helper/query-state.jsx';
import { formatDateTime } from '/format-date.js';

/**
 * The admins' review queue (api.listPendingApprovals), with approve and reject
 * per version and a link to the exact commit's source. An approval is bound to
 * the commit the tag pointed to when it was submitted; if the tag moved since,
 * the API refuses the approval (409 version_moved) and the author has to
 * submit again. Non-admins get a notice instead.
 */
export function AdminApprovals() {
    const { t } = useTranslation();
    const api = useAppStoreApi();
    const { isAdmin, query: meQuery } = useMe();
    const [rejecting, setRejecting] = useState(null);

    const query = useQuery({ queryKey: appstoreKeys.pendingApprovals(), queryFn: api.listPendingApprovals, enabled: isAdmin });
    const invalidates = [appstoreKeys.pendingApprovals(), appstoreKeys.apps()];
    const approve = useApiMutation({ mutationFn: (a) => api.approveVersion(a.appId, a.version_tag), invalidates });

    if (meQuery.isSuccess && !isAdmin) {
        return <Container py="xl"><Alert color="yellow">{t('appstore.admin.notAdmin')}</Alert></Container>;
    }

    return (
        <Container size="lg" py="xl">
            <Stack gap="md">
                <Title order={2}>{t('appstore.admin.title')}</Title>
                <Text size="sm" c="dimmed">{t('appstore.admin.intro')}</Text>
                {query.isPending && isAdmin && <Loading />}
                {query.isError && <LoadError query={query} />}
                {query.isSuccess && query.data.length === 0 && <Alert color="gray">{t('appstore.admin.empty')}</Alert>}
                {query.data?.map(a => (
                    <Card key={a.approvalId} withBorder>
                        <Group justify="space-between" align="flex-start">
                            <Stack gap={4}>
                                <Anchor component={Link} href={`/apps/${a.appId}`} fw={600}>{a.app?.name}</Anchor>
                                <Text size="sm">{t('appstore.admin.versionAt', { version: a.version_tag })} <Code>{a.commit_sha.slice(0, 12)}</Code></Text>
                                {a.app?.git_link && (
                                    <Anchor size="sm" href={`${a.app.git_link.replace(/\.git$/, '')}/tree/${a.commit_sha}`} target="_blank" rel="noopener noreferrer">
                                        {t('appstore.admin.viewSource')}
                                    </Anchor>
                                )}
                                {a.notes && <Text size="sm" c="dimmed">{a.notes}</Text>}
                                <Text size="xs" c="dimmed">{t('appstore.admin.submittedAt', { date: formatDateTime(a.created_at) })}</Text>
                            </Stack>
                            <Group gap="xs">
                                <Button size="xs" color="green" leftSection={<Check size={14} />}
                                    loading={approve.isPending && approve.variables?.approvalId === a.approvalId}
                                    onClick={() => approve.mutate(a)}>
                                    {t('appstore.admin.approve')}
                                </Button>
                                <Button size="xs" color="red" variant="light" leftSection={<X size={14} />} onClick={() => setRejecting(a)}>
                                    {t('appstore.admin.reject')}
                                </Button>
                            </Group>
                        </Group>
                    </Card>
                ))}
            </Stack>
            {rejecting && <RejectModal approval={rejecting} onClose={() => setRejecting(null)} />}
        </Container>
    );
}

/** Modal asking for the (required) reason, then rejecting the version via api.rejectVersion. */
function RejectModal({ approval, onClose }) {
    const { t } = useTranslation();
    const api = useAppStoreApi();
    const [reason, setReason] = useState('');
    const reject = useApiMutation({
        mutationFn: () => api.rejectVersion(approval.appId, approval.version_tag, reason.trim()),
        invalidates: [appstoreKeys.pendingApprovals()],
        onSuccess: onClose,
        reportErrors: 'inline',
    });
    return (
        <Modal opened onClose={onClose} title={t('appstore.admin.rejectTitle', { name: approval.app?.name ?? '', version: approval.version_tag })}>
            <Stack gap="sm">
                <Textarea label={t('appstore.admin.reason')} description={t('appstore.admin.reasonHint')}
                    value={reason} onChange={(e) => setReason(e.currentTarget.value)} autosize minRows={3} required />
                {reject.error && <Alert color="red">{reject.error.message}</Alert>}
                <Group justify="flex-end">
                    <Button variant="default" onClick={onClose}>{t('appstore.common.cancel')}</Button>
                    <Button color="red" onClick={() => reject.mutate()} loading={reject.isPending} disabled={!reason.trim()}>
                        {t('appstore.admin.reject')}
                    </Button>
                </Group>
            </Stack>
        </Modal>
    );
}
