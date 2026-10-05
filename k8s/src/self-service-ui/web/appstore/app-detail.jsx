import { useState } from 'react';
import { Alert, Anchor, Badge, Button, Card, Code, Container, Group, Image, Modal, Stack, Switch, Table, Text, Textarea, TextInput, Title } from '@mantine/core';
import { useQuery } from '@tanstack/react-query';
import { ArrowLeft, Ban, Pencil, Rocket, Send, Trash2, Undo2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Link, useLocation } from 'wouter';
import { useAppStoreApi } from '/appstore/api-appstore.jsx';
import { appstoreKeys } from '/appstore/query-keys.js';
import { useMe } from '/appstore/use-appstore.jsx';
import { Markdown } from '/appstore/markdown.jsx';
import { LoadError, Loading, useApiMutation } from '/helper/query-state.jsx';
import { useConfirm } from '/providers/confirm.jsx';
import { formatDateTime } from '/format-date.js';

// One app: its description, its versions and, for its owner (and admins), the
// review state of each version. A public app deploys only versions an admin
// approved for exactly their current commit; a private app deploys any tag,
// for its owner only (plan E6).

const APPROVAL_COLOR = { approved: 'green', pending: 'yellow', rejected: 'red' };

/**
 * The app page (/appstore/apps/:appId): description, versions with deploy
 * buttons, and for owner and admins the review state (api.listApprovals) with
 * submit/withdraw, edit and delete.
 */
export function AppDetail({ params }) {
    const { t } = useTranslation();
    const api = useAppStoreApi();
    const [, navigate] = useLocation();
    const confirm = useConfirm();
    const { me, isAdmin, canDeploy } = useMe();
    const [editing, setEditing] = useState(false);
    const appId = params.appId;

    const query = useQuery({ queryKey: appstoreKeys.app(appId), queryFn: () => api.getApp(appId) });
    const app = query.data;
    // By id, like everywhere else: addresses can differ in case.
    const isOwner = Boolean(app && me?.userId && String(app.userId) === String(me.userId));
    const canManage = isOwner || isAdmin;

    const approvals = useQuery({
        queryKey: appstoreKeys.approvals(appId),
        queryFn: () => api.listApprovals(appId),
        enabled: canManage,
    });
    const approvalOf = Object.fromEntries((approvals.data ?? []).map(a => [a.version_tag, a]));

    const invalidates = [appstoreKeys.app(appId), appstoreKeys.approvals(appId), appstoreKeys.apps(), appstoreKeys.pendingApprovals()];
    const submit = useApiMutation({ mutationFn: (tag) => api.submitVersion(appId, tag), invalidates });
    const withdraw = useApiMutation({ mutationFn: (tag) => api.withdrawVersion(appId, tag), invalidates });
    const block = useApiMutation({ mutationFn: () => api.deactivateApp(appId), invalidates });
    const remove = useApiMutation({
        mutationFn: () => api.deleteApp(appId),
        invalidates: [appstoreKeys.apps()],
        onSuccess: () => navigate('/catalog'),
    });

    if (query.isPending) return <Container py="xl"><Loading /></Container>;
    if (query.isError) return <Container py="xl"><LoadError query={query} /></Container>;

    const versions = app.versions ?? [];

    return (
        <Container size="lg" py="xl">
            <Stack gap="md">
                <Anchor component={Link} href="/catalog" size="sm"><Group gap={4}><ArrowLeft size={14} />{t('appstore.appDetail.back')}</Group></Anchor>
                <Group justify="space-between" align="flex-start">
                    <Group wrap="nowrap">
                        {app.image && <Image src={app.image} w={64} h={64} fit="contain" alt="" />}
                        <Stack gap={4}>
                            <Title order={2}>{app.name}</Title>
                            <Group gap="xs">
                                {app.is_private && <Badge variant="outline" color="gray">{t('appstore.catalog.private')}</Badge>}
                                <Text size="sm" c="dimmed">{t('appstore.appDetail.owner', { email: app.user?.email ?? '' })}</Text>
                            </Group>
                            {app.git_link && <Anchor href={app.git_link} target="_blank" rel="noopener noreferrer" size="sm">{app.git_link}</Anchor>}
                        </Stack>
                    </Group>
                    <Group gap="xs">
                        {canManage && (
                            <Button variant="default" leftSection={<Pencil size={16} />} onClick={() => setEditing(true)}>
                                {t('appstore.appDetail.edit')}
                            </Button>
                        )}
                        {isAdmin && !app.hidden_by_admin && (
                            <Button variant="light" color="orange" leftSection={<Ban size={16} />} loading={block.isPending}
                                onClick={async () => {
                                    if (await confirm({ title: t('appstore.appDetail.blockTitle'), message: t('appstore.appDetail.blockMessage', { name: app.name }), confirmLabel: t('appstore.appDetail.block') })) block.mutate();
                                }}>
                                {t('appstore.appDetail.block')}
                            </Button>
                        )}
                        {canManage && (
                            <Button variant="light" color="red" leftSection={<Trash2 size={16} />} loading={remove.isPending}
                                onClick={async () => {
                                    if (await confirm({ title: t('appstore.appDetail.deleteTitle'), message: t('appstore.appDetail.deleteMessage', { name: app.name }) })) remove.mutate();
                                }}>
                                {t('appstore.appDetail.delete')}
                            </Button>
                        )}
                    </Group>
                </Group>

                {app.hidden_by_admin && <Alert color="orange">{t('appstore.appDetail.hiddenByAdmin')}</Alert>}

                {app.description
                    ? <Card withBorder padding="lg"><Markdown source={app.description} /></Card>
                    : <Text c="dimmed">{t('appstore.appDetail.noDescription')}</Text>}

                <Title order={3}>{t('appstore.appDetail.versions')}</Title>
                {versions.length === 0 ? (
                    <Alert color="gray">{canManage ? t('appstore.appDetail.noTags') : t('appstore.appDetail.noApprovedVersion')}</Alert>
                ) : (
                    <Table striped withTableBorder>
                        <Table.Thead>
                            <Table.Tr>
                                <Table.Th>{t('appstore.appDetail.version')}</Table.Th>
                                <Table.Th>{t('appstore.appDetail.commit')}</Table.Th>
                                {canManage && <Table.Th>{t('appstore.appDetail.review')}</Table.Th>}
                                <Table.Th />
                            </Table.Tr>
                        </Table.Thead>
                        <Table.Tbody>
                            {versions.map(v => {
                                const approval = approvalOf[v.version];
                                const deployable = v.approved || (app.is_private && isOwner);
                                return (
                                    <Table.Tr key={v.version}>
                                        <Table.Td><Text fw={500}>{v.version}</Text></Table.Td>
                                        <Table.Td><Code>{String(v.sha ?? v.commit ?? '').slice(0, 8)}</Code></Table.Td>
                                        {canManage && (
                                            <Table.Td>
                                                {v.approved
                                                    ? <Badge color="green" variant="light">{t('appstore.approval.approved')}</Badge>
                                                    : approval
                                                        ? <Badge color={APPROVAL_COLOR[approval.status] ?? 'gray'} variant="light" title={approval.rejection_reason ?? ''}>{t(`appstore.approval.${approval.status}`, { defaultValue: approval.status })}</Badge>
                                                        : <Text size="sm" c="dimmed">{app.is_private ? t('appstore.appDetail.privateNoReview') : t('appstore.approval.none')}</Text>}
                                            </Table.Td>
                                        )}
                                        <Table.Td>
                                            <Group gap="xs" justify="flex-end">
                                                {isOwner && !app.is_private && !v.approved && approval?.status !== 'pending' && (
                                                    <Button size="xs" variant="light" leftSection={<Send size={14} />} loading={submit.isPending && submit.variables === v.version}
                                                        onClick={() => submit.mutate(v.version)}>
                                                        {t('appstore.appDetail.submit')}
                                                    </Button>
                                                )}
                                                {isOwner && approval?.status === 'pending' && (
                                                    <Button size="xs" variant="subtle" leftSection={<Undo2 size={14} />} loading={withdraw.isPending && withdraw.variables === v.version}
                                                        onClick={() => withdraw.mutate(v.version)}>
                                                        {t('appstore.appDetail.withdraw')}
                                                    </Button>
                                                )}
                                                {canDeploy && deployable && (
                                                    <Button size="xs" component={Link} href={`/deploy/${app.appId}?version=${encodeURIComponent(v.version)}`} leftSection={<Rocket size={14} />}>
                                                        {t('appstore.catalog.deploy')}
                                                    </Button>
                                                )}
                                            </Group>
                                        </Table.Td>
                                    </Table.Tr>
                                );
                            })}
                        </Table.Tbody>
                    </Table>
                )}
                {approvals.data?.some(a => a.status === 'rejected') && (
                    <Stack gap={4}>
                        {approvals.data.filter(a => a.status === 'rejected' && a.rejection_reason).map(a => (
                            <Text key={a.approvalId} size="sm" c="red">
                                {t('appstore.appDetail.rejectedBecause', { version: a.version_tag, reason: a.rejection_reason, date: formatDateTime(a.reviewed_at) })}
                            </Text>
                        ))}
                    </Stack>
                )}
            </Stack>
            {editing && <EditAppModal app={app} isAdmin={isAdmin} onClose={() => setEditing(false)} />}
        </Container>
    );
}

/**
 * Modal editing an app's name, description and visibility via api.updateApp.
 * An app an admin blocked stays private unless an admin edits it.
 */
function EditAppModal({ app, isAdmin, onClose }) {
    const { t } = useTranslation();
    const api = useAppStoreApi();
    const [name, setName] = useState(app.name);
    const [description, setDescription] = useState(app.description ?? '');
    const [isPrivate, setIsPrivate] = useState(app.is_private);
    const save = useApiMutation({
        mutationFn: () => api.updateApp(app.appId, { name: name.trim(), description, is_private: isPrivate }),
        invalidates: [appstoreKeys.app(app.appId), appstoreKeys.apps()],
        onSuccess: onClose,
        reportErrors: 'inline',
    });

    return (
        <Modal opened onClose={onClose} title={t('appstore.appDetail.editTitle')} size="lg">
            <Stack gap="sm">
                <TextInput label={t('appstore.registerApp.name')} value={name} onChange={(e) => setName(e.currentTarget.value)} required />
                <Textarea label={t('appstore.registerApp.description')} description={t('appstore.registerApp.markdownHint')}
                    value={description} onChange={(e) => setDescription(e.currentTarget.value)} autosize minRows={6} />
                <Switch label={t('appstore.registerApp.private')}
                    description={app.hidden_by_admin && !isAdmin ? t('appstore.appDetail.hiddenByAdmin') : t('appstore.registerApp.privateHint')}
                    disabled={app.hidden_by_admin && !isAdmin}
                    checked={isPrivate} onChange={(e) => setIsPrivate(e.currentTarget.checked)} />
                {save.error && <Alert color="red">{save.error.message}</Alert>}
                <Group justify="flex-end">
                    <Button variant="default" onClick={onClose}>{t('appstore.common.cancel')}</Button>
                    <Button onClick={() => save.mutate()} loading={save.isPending} disabled={!name.trim()}>{t('appstore.common.save')}</Button>
                </Group>
            </Stack>
        </Modal>
    );
}
