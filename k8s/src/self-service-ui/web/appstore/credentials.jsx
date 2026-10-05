// AppStore page "OpenStack credentials" (/appstore/credentials): list, add,
// test, delete and show the quota of the caller's stored credentials.
import { useState } from 'react';
import { Alert, Badge, Button, Card, Code, Container, Group, Modal, Progress, SegmentedControl, SimpleGrid, Stack, Text, Textarea, TextInput, Title } from '@mantine/core';
import { useQuery } from '@tanstack/react-query';
import { BarChart3, KeyRound, Plus, RefreshCw, Trash2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useAppStoreApi } from '/appstore/api-appstore.jsx';
import { appstoreKeys } from '/appstore/query-keys.js';
import { LoadError, Loading, useApiMutation } from '/helper/query-state.jsx';
import { useConfirm } from '/providers/confirm.jsx';
import { formatDateTime } from '/format-date.js';

/**
 * The caller's OpenStack credentials, one per project (plan AP5). A credential
 * is stored only after Keystone accepted it, and its project is the one
 * Keystone scoped it to — which is what makes everyone with a credential for
 * the same project a peer who sees and runs its deployments (E2). Adding one
 * for a project that already has one replaces it: that is how a secret is
 * rotated.
 */
export function Credentials() {
    const { t } = useTranslation();
    const api = useAppStoreApi();
    const confirm = useConfirm();
    const [adding, setAdding] = useState(false);
    const query = useQuery({ queryKey: appstoreKeys.credentials(), queryFn: api.listCredentials });

    const invalidates = [appstoreKeys.credentials()];
    const test = useApiMutation({ mutationFn: (id) => api.testCredential(id), invalidates });
    const remove = useApiMutation({ mutationFn: (id) => api.deleteCredential(id), invalidates });

    return (
        <Container size="lg" py="xl">
            <Stack gap="md">
                <Group justify="space-between">
                    <Title order={2}>{t('appstore.credentials.title')}</Title>
                    <Button leftSection={<Plus size={16} />} onClick={() => setAdding(true)}>{t('appstore.credentials.add')}</Button>
                </Group>
                <Text size="sm" c="dimmed">{t('appstore.credentials.intro')}</Text>

                {query.isPending && <Loading />}
                {query.isError && <LoadError query={query} />}
                {query.isSuccess && query.data.length === 0 && (
                    <Alert color="blue" icon={<KeyRound size={16} />} title={t('appstore.credentials.emptyTitle')}>
                        {t('appstore.credentials.emptyMessage')}
                    </Alert>
                )}
                {query.data?.map(c => (
                    <CredentialCard key={c.credentialId} credential={c}
                        testing={test.isPending && test.variables === c.credentialId}
                        onTest={() => test.mutate(c.credentialId)}
                        onDelete={async () => {
                            if (await confirm({
                                title: t('appstore.credentials.deleteTitle'),
                                message: t('appstore.credentials.deleteMessage', { project: c.project_name || c.project_id }),
                            })) remove.mutate(c.credentialId);
                        }} />
                ))}
            </Stack>
            {adding && <AddCredentialModal onClose={() => setAdding(false)} />}
        </Container>
    );
}

/**
 * One credential: project, auth type, result of the last validation, and
 * test/quota/delete buttons. Delete is disabled while deployments use it
 * (`active_deployments`), which the API would refuse anyway.
 */
function CredentialCard({ credential: c, testing, onTest, onDelete }) {
    const { t } = useTranslation();
    const [quotaOpen, setQuotaOpen] = useState(false);
    const locked = (c.active_deployments ?? 0) > 0;
    return (
        <Card withBorder>
            <Stack gap="xs">
                <Group justify="space-between" align="flex-start">
                    <Stack gap={2}>
                        <Text fw={600}>{c.project_name || c.project_id}</Text>
                        <Text size="sm" c="dimmed">{t('appstore.credentials.projectId')} <Code>{c.project_id}</Code></Text>
                        <Text size="xs" c="dimmed">{c.auth_url}{c.region_name ? ` · ${c.region_name}` : ''}</Text>
                    </Stack>
                    <Group gap="xs">
                        <Badge variant="light">{t(`appstore.credentials.type.${c.auth_type}`, { defaultValue: c.auth_type })}</Badge>
                        {c.last_validation_error
                            ? <Badge color="red" variant="light">{t('appstore.credentials.invalid')}</Badge>
                            : <Badge color="green" variant="light">{t('appstore.credentials.valid')}</Badge>}
                    </Group>
                </Group>
                <Text size="xs" c="dimmed">
                    {c.last_validation_error
                        ? t('appstore.credentials.lastError', { cause: t(`appstore.errors.causes.${c.last_validation_error}`, { defaultValue: c.last_validation_error }) })
                        : t('appstore.credentials.checkedAt', { date: formatDateTime(c.last_validated_at) })}
                </Text>
                {locked && <Text size="xs">{t('appstore.credentials.inUse', { count: c.active_deployments })}</Text>}
                <Group gap="xs">
                    <Button size="xs" variant="default" leftSection={<RefreshCw size={14} />} loading={testing} onClick={onTest}>
                        {t('appstore.credentials.test')}
                    </Button>
                    <Button size="xs" variant="default" leftSection={<BarChart3 size={14} />} onClick={() => setQuotaOpen(o => !o)}>
                        {t('appstore.credentials.quota')}
                    </Button>
                    <Button size="xs" variant="light" color="red" leftSection={<Trash2 size={14} />} disabled={locked} onClick={onDelete}
                        title={locked ? t('appstore.credentials.lockedHint') : undefined}>
                        {t('appstore.credentials.delete')}
                    </Button>
                </Group>
                {quotaOpen && <Quota credentialId={c.credentialId} />}
            </Stack>
        </Card>
    );
}

const QUOTA_ROWS = [
    ['compute', 'instances'], ['compute', 'vcpus'], ['compute', 'ram'],
    ['storage', 'volumes'], ['storage', 'gigabytes'],
    ['network', 'floating_ips'], ['network', 'security_groups'], ['network', 'networks'],
];

/** The project's quota usage (api.getQuota) as progress bars; a negative limit means unlimited. */
function Quota({ credentialId }) {
    const { t } = useTranslation();
    const api = useAppStoreApi();
    const query = useQuery({ queryKey: appstoreKeys.quota(credentialId), queryFn: () => api.getQuota(credentialId) });
    if (query.isPending) return <Loading size="sm" />;
    if (query.isError) return <LoadError query={query} />;
    return (
        <SimpleGrid cols={{ base: 1, sm: 2 }} mt="xs">
            {QUOTA_ROWS.map(([group, key]) => {
                const q = query.data[group]?.[key];
                if (!q) return null;
                const pct = q.limit > 0 ? Math.min(100, (q.used / q.limit) * 100) : 0;
                return (
                    <Stack key={`${group}.${key}`} gap={2}>
                        <Group justify="space-between">
                            <Text size="sm">{t(`appstore.quota.${key}`)}</Text>
                            <Text size="sm" c="dimmed">{`${q.used} / ${q.limit < 0 ? '∞' : q.limit}${q.unit ? ` ${q.unit}` : ''}`}</Text>
                        </Group>
                        <Progress value={pct} color={pct > 90 ? 'red' : pct > 70 ? 'yellow' : 'blue'} size="sm" />
                    </Stack>
                );
            })}
        </SimpleGrid>
    );
}

const EMPTY_FORM = {
    auth_type: 'v3applicationcredential', auth_url: '', region_name: '', identifier: '', secret: '',
    project_name: '', user_domain_name: 'Default', project_domain_name: 'Default',
};

/**
 * Modal adding a credential, either from a form (application credential or
 * username/password) or from a pasted clouds.yaml. The API validates it
 * against Keystone before storing it.
 */
function AddCredentialModal({ onClose }) {
    const { t } = useTranslation();
    const api = useAppStoreApi();
    const [mode, setMode] = useState('form');
    const [form, setForm] = useState(EMPTY_FORM);
    const [yaml, setYaml] = useState('');
    const [cloudName, setCloudName] = useState('');
    const set = (key) => (e) => setForm(f => ({ ...f, [key]: e.currentTarget.value }));
    const isPassword = form.auth_type === 'password';

    const save = useApiMutation({
        mutationFn: () => (mode === 'yaml'
            ? api.saveCredentialFromYaml(yaml, cloudName.trim())
            : api.saveCredential({
                auth_type: form.auth_type,
                auth_url: form.auth_url.trim(),
                region_name: form.region_name.trim() || null,
                identifier: form.identifier.trim(),
                secret: form.secret,
                ...(isPassword ? {
                    project_name: form.project_name.trim() || null,
                    user_domain_name: form.user_domain_name.trim() || null,
                    project_domain_name: form.project_domain_name.trim() || null,
                } : {}),
            })),
        invalidates: [appstoreKeys.credentials()],
        onSuccess: onClose,
        reportErrors: 'inline',
    });

    const complete = mode === 'yaml'
        ? yaml.trim() !== ''
        : form.auth_url.trim() && form.identifier.trim() && form.secret && (!isPassword || form.project_name.trim());

    return (
        <Modal opened onClose={onClose} title={t('appstore.credentials.addTitle')} size="lg">
            <Stack gap="sm">
                <SegmentedControl value={mode} onChange={setMode} data={[
                    { value: 'form', label: t('appstore.credentials.modeForm') },
                    { value: 'yaml', label: t('appstore.credentials.modeYaml') },
                ]} />
                {mode === 'yaml' ? (
                    <>
                        <Textarea label="clouds.yaml" description={t('appstore.credentials.yamlHint')} value={yaml}
                            onChange={(e) => setYaml(e.currentTarget.value)} autosize minRows={8} ff="monospace" />
                        <TextInput label={t('appstore.credentials.cloudName')} description={t('appstore.credentials.cloudNameHint')}
                            value={cloudName} onChange={(e) => setCloudName(e.currentTarget.value)} />
                    </>
                ) : (
                    <>
                        <SegmentedControl value={form.auth_type} onChange={(v) => setForm(f => ({ ...f, auth_type: v }))} data={[
                            { value: 'v3applicationcredential', label: t('appstore.credentials.type.v3applicationcredential') },
                            { value: 'password', label: t('appstore.credentials.type.password') },
                        ]} />
                        <Text size="xs" c="dimmed">
                            {isPassword ? t('appstore.credentials.passwordHint') : t('appstore.credentials.appCredentialHint')}
                        </Text>
                        <TextInput label={t('appstore.credentials.authUrl')} placeholder="https://keystone.example/v3"
                            value={form.auth_url} onChange={set('auth_url')} required />
                        <TextInput label={t('appstore.credentials.region')} value={form.region_name} onChange={set('region_name')} />
                        <TextInput label={isPassword ? t('appstore.credentials.username') : t('appstore.credentials.appCredentialId')}
                            value={form.identifier} onChange={set('identifier')} required />
                        <TextInput type="password" label={isPassword ? t('appstore.credentials.password') : t('appstore.credentials.appCredentialSecret')}
                            value={form.secret} onChange={set('secret')} required autoComplete="off" />
                        {isPassword && (
                            <>
                                <TextInput label={t('appstore.credentials.projectName')} value={form.project_name} onChange={set('project_name')} required />
                                <Group grow>
                                    <TextInput label={t('appstore.credentials.userDomain')} value={form.user_domain_name} onChange={set('user_domain_name')} />
                                    <TextInput label={t('appstore.credentials.projectDomain')} value={form.project_domain_name} onChange={set('project_domain_name')} />
                                </Group>
                            </>
                        )}
                    </>
                )}
                {save.error && <Alert color="red">{save.error.message}</Alert>}
                <Group justify="flex-end">
                    <Button variant="default" onClick={onClose}>{t('appstore.common.cancel')}</Button>
                    <Button onClick={() => save.mutate()} loading={save.isPending} disabled={!complete}>{t('appstore.credentials.checkAndSave')}</Button>
                </Group>
            </Stack>
        </Modal>
    );
}
