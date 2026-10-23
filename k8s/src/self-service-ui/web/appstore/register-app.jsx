// AppStore page "register app" (/appstore/apps/new), reached from the catalogue.
import { useState } from 'react';
import { Alert, Button, Container, Group, Stack, Switch, Text, Textarea, TextInput, Title } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { useLocation } from 'wouter';
import { useAppStoreApi } from '/appstore/api-appstore.jsx';
import { appstoreKeys } from '/appstore/query-keys.js';
import { useMe } from '/appstore/use-appstore.jsx';
import { useApiMutation } from '/helper/query-state.jsx';

/**
 * Registering an app: a public Git repository (the API's host allowlist
 * decides which hosts), a name and a Markdown description. A private app is
 * its owner's test bench and deploys any tag; a public one needs every version
 * approved by an admin, which "submit all tags" requests right away.
 * Calls api.createApp and navigates to the new app on success; shown only to
 * callers with `can_register_apps`.
 */
export function RegisterApp() {
    const { t } = useTranslation();
    const api = useAppStoreApi();
    const [, navigate] = useLocation();
    const { canRegisterApps, query: meQuery } = useMe();
    const [form, setForm] = useState({ name: '', git_link: '', description: '', is_private: true, submit_all_versions: false });
    // Read the event now: React clears `currentTarget` once the handler returns,
    // and the state updater below runs later.
    const set = (key) => (e) => {
        const value = e?.currentTarget ? (e.currentTarget.type === 'checkbox' ? e.currentTarget.checked : e.currentTarget.value) : e;
        setForm(f => ({ ...f, [key]: value }));
    };

    const create = useApiMutation({
        mutationFn: () => api.createApp({
            ...form,
            name: form.name.trim(),
            git_link: form.git_link.trim(),
            submit_all_versions: !form.is_private && form.submit_all_versions,
        }),
        invalidates: [appstoreKeys.apps()],
        onSuccess: (app) => navigate(`/apps/${app.appId}`),
        reportErrors: 'inline',
    });

    if (meQuery.isSuccess && !canRegisterApps) {
        return <Container py="xl"><Alert color="yellow">{t('appstore.registerApp.notAllowed')}</Alert></Container>;
    }

    return (
        <Container size="md" py="xl">
            <Stack gap="md">
                <Title order={2}>{t('appstore.registerApp.title')}</Title>
                <Text size="sm" c="dimmed">{t('appstore.registerApp.intro')}</Text>
                <TextInput label={t('appstore.registerApp.name')} value={form.name} onChange={set('name')} required />
                <TextInput label={t('appstore.registerApp.gitLink')} description={t('appstore.registerApp.gitLinkHint')}
                    placeholder="https://github.com/org/app" value={form.git_link} onChange={set('git_link')} required />
                <Textarea label={t('appstore.registerApp.description')} description={t('appstore.registerApp.markdownHint')}
                    value={form.description} onChange={set('description')} autosize minRows={6} />
                <Switch label={t('appstore.registerApp.private')} description={t('appstore.registerApp.privateHint')}
                    checked={form.is_private} onChange={set('is_private')} />
                {!form.is_private && (
                    <Switch label={t('appstore.registerApp.submitAll')} description={t('appstore.registerApp.submitAllHint')}
                        checked={form.submit_all_versions} onChange={set('submit_all_versions')} />
                )}
                {create.error && <Alert color="red">{create.error.message}</Alert>}
                <Group justify="flex-end">
                    <Button onClick={() => create.mutate()} loading={create.isPending}
                        disabled={!form.name.trim() || !form.git_link.trim()}>
                        {t('appstore.registerApp.submit')}
                    </Button>
                </Group>
            </Stack>
        </Container>
    );
}
