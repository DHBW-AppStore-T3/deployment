import { useMemo, useState } from 'react';
import { Alert, Anchor, Badge, Button, Card, Container, Group, Image, SimpleGrid, Stack, Text, TextInput, Title } from '@mantine/core';
import { useQuery } from '@tanstack/react-query';
import { Plus, Rocket, Search } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Link } from 'wouter';
import { useAppStoreApi } from '/appstore/api-appstore.jsx';
import { appstoreKeys } from '/appstore/query-keys.js';
import { useMe } from '/appstore/use-appstore.jsx';
import { LoadError, Loading } from '/helper/query-state.jsx';

// The catalogue: every app the caller may see — public apps with an approved
// version, and their own private ones (the API decides which).

/** The catalogue search: true if every word of `search` occurs in the app's name or description, in any order. */
export function matches(app, search) {
    const words = search.toLowerCase().split(/\s+/).filter(Boolean);
    const text = `${app.name} ${app.description ?? ''}`.toLowerCase();
    return words.every(w => text.includes(w));
}

/**
 * The first paragraph of a Markdown description (skipping headings), as plain
 * text for a card, cut to `max` characters with an ellipsis.
 */
export function teaser(description, max = 160) {
    const first = String(description ?? '').split(/\n\s*\n/).find(p => p.trim() && !p.trim().startsWith('#')) ?? '';
    const plain = first.replace(/[#*_`>[\]]/g, '').replace(/\(([^)]*)\)/g, '').replace(/\s+/g, ' ').trim();
    return plain.length > max ? `${plain.slice(0, max - 1)}…` : plain;
}

/**
 * The catalogue page (/appstore/catalog): a searchable grid of app cards from
 * api.listApps. "Register" and "Deploy" buttons follow the caller's rights (useMe).
 */
export function Catalog() {
    const { t } = useTranslation();
    const api = useAppStoreApi();
    const { canDeploy, canRegisterApps } = useMe();
    const [search, setSearch] = useState('');
    const query = useQuery({ queryKey: appstoreKeys.apps(), queryFn: api.listApps });

    const apps = useMemo(
        () => (query.data ?? []).filter(a => matches(a, search)).sort((a, b) => a.name.localeCompare(b.name)),
        [query.data, search],
    );

    return (
        <Container size="xl" py="xl">
            <Stack gap="md">
                <Group justify="space-between">
                    <Title order={2}>{t('appstore.catalog.title')}</Title>
                    {canRegisterApps && (
                        <Button component={Link} href="/apps/new" leftSection={<Plus size={16} />} variant="light">
                            {t('appstore.catalog.register')}
                        </Button>
                    )}
                </Group>
                <TextInput leftSection={<Search size={16} />} placeholder={t('appstore.catalog.search')}
                    value={search} onChange={(e) => setSearch(e.currentTarget.value)} maw={420} />

                {query.isPending && <Loading />}
                {query.isError && <LoadError query={query} />}
                {query.isSuccess && apps.length === 0 && (
                    <Alert color="gray">{search ? t('appstore.catalog.noMatch') : t('appstore.catalog.empty')}</Alert>
                )}

                <SimpleGrid cols={{ base: 1, sm: 2, lg: 3 }}>
                    {apps.map(app => (
                        <Card key={app.appId} withBorder padding="lg">
                            <Stack gap="sm" h="100%">
                                <Group wrap="nowrap" align="flex-start">
                                    {app.image && <Image src={app.image} w={48} h={48} fit="contain" alt="" />}
                                    <Stack gap={2}>
                                        <Anchor fw={600} component={Link} href={`/apps/${app.appId}`}>{app.name}</Anchor>
                                        {app.is_private && <Badge size="xs" variant="outline" color="gray">{t('appstore.catalog.private')}</Badge>}
                                    </Stack>
                                </Group>
                                <Text size="sm" c="dimmed" style={{ flexGrow: 1 }}>{teaser(app.description)}</Text>
                                <Group gap="xs">
                                    <Button component={Link} href={`/apps/${app.appId}`} variant="default" size="xs">
                                        {t('appstore.catalog.details')}
                                    </Button>
                                    {canDeploy && (
                                        <Button component={Link} href={`/deploy/${app.appId}`} size="xs" leftSection={<Rocket size={14} />}>
                                            {t('appstore.catalog.deploy')}
                                        </Button>
                                    )}
                                </Group>
                            </Stack>
                        </Card>
                    ))}
                </SimpleGrid>
            </Stack>
        </Container>
    );
}
