import { useMemo, useState } from 'react';
import { Accordion, ActionIcon, Alert, Anchor, Badge, Button, Card, Code, Group, MultiSelect, NumberInput, SegmentedControl, Select, Stack, Table, Text, TextInput, Title } from '@mantine/core';
import { Plus, Shuffle, Trash2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Link } from 'wouter';
import { FileField, MarkerError, ValueField } from '/appstore/wizard/fields.jsx';
import {
    distribute, formKey, isFileVar, isMultiImage, missingRequired, scopeOf, slotKeys, teamProblems, teamsOfSize,
} from '/appstore/wizard-logic.js';

// The four steps of the deploy wizard. Each is a plain component on the
// wizard's state (deploy-wizard.jsx); the rules live in wizard-logic.js.

// ── 1. Basics ───────────────────────────────────────────────────────────

/**
 * Name, version, credential and course. Changing the course clears the teams,
 * since they were built from the previous course's students.
 */
export function StepBasics({ state, set, app, versions, credentials, courses }) {
    const { t } = useTranslation();
    return (
        <Stack gap="md" maw={640}>
            <TextInput label={t('appstore.wizard.name')} description={t('appstore.wizard.nameHint')} required
                value={state.name} onChange={(e) => set({ name: e.currentTarget.value })} />
            <Select label={t('appstore.wizard.version')} required data={versions.map(v => ({ value: v.version, label: v.version }))}
                value={state.version} onChange={(version) => set({ version })}
                description={app?.is_private ? t('appstore.wizard.versionPrivate') : t('appstore.wizard.versionApproved')} />
            {credentials.length === 0 ? (
                <Alert color="yellow" title={t('appstore.wizard.noCredentialTitle')}>
                    {t('appstore.wizard.noCredentialMessage')} <Anchor component={Link} href="/credentials">{t('appstore.nav.credentials')}</Anchor>
                </Alert>
            ) : (
                <Select label={t('appstore.wizard.credential')} required description={t('appstore.wizard.credentialHint')}
                    data={credentials.map(c => ({ value: c.credentialId, label: c.project_name || c.project_id }))}
                    value={state.credentialId} onChange={(credentialId) => set({ credentialId })} />
            )}
            {courses.length === 0 ? (
                <Alert color="yellow">{t('appstore.wizard.noCourse')}</Alert>
            ) : (
                <Select label={t('appstore.wizard.course')} required description={t('appstore.wizard.courseHint')}
                    data={courses.map(c => ({ value: c.course, label: c.display_name }))}
                    value={state.course} onChange={(course) => set({ course, teams: [] })} />
            )}
        </Stack>
    );
}

/** Whether step 1 has everything it needs (name, version, credential, course). */
export function basicsComplete(state) {
    return Boolean(state.name.trim() && state.version && state.credentialId && state.course);
}

// ── 2. Teams ────────────────────────────────────────────────────────────

/**
 * Teams are built from the course's students (role-provider-service, via the
 * API), by automatic distribution or by hand. Each person in at most one team;
 * no team at all is fine for apps that need none.
 */
export function StepTeams({ state, set, students, studentsQuery }) {
    const { t } = useTranslation();
    const [how, setHow] = useState('count');
    const [n, setN] = useState(2);
    const teams = state.teams;
    const assigned = new Set(teams.flatMap(tm => tm.emails));
    const unassigned = students.filter(s => !assigned.has(s));
    const problems = teamProblems(teams);

    const setTeams = (next) => set({ teams: next });
    const update = (i, patch) => setTeams(teams.map((tm, j) => (j === i ? { ...tm, ...patch } : tm)));

    if (studentsQuery.isError) {
        return <Alert color="red">{studentsQuery.error.message}</Alert>;
    }

    return (
        <Stack gap="md">
            <Text size="sm" c="dimmed">{t('appstore.wizard.teamsIntro', { count: students.length })}</Text>
            <Card withBorder>
                <Group align="flex-end">
                    <SegmentedControl value={how} onChange={setHow} data={[
                        { value: 'count', label: t('appstore.wizard.byCount') },
                        { value: 'size', label: t('appstore.wizard.bySize') },
                    ]} />
                    <NumberInput w={120} min={1} value={n} onChange={(x) => setN(Number(x) || 1)}
                        label={how === 'count' ? t('appstore.wizard.teamCount') : t('appstore.wizard.teamSize')} />
                    <Button leftSection={<Shuffle size={16} />} variant="light" disabled={!students.length}
                        onClick={() => setTeams(how === 'count' ? distribute(students, n) : teamsOfSize(students, n))}>
                        {t('appstore.wizard.distribute')}
                    </Button>
                    <Button variant="subtle" leftSection={<Plus size={16} />}
                        onClick={() => setTeams([...teams, { name: `Team-${teams.length + 1}`, emails: [] }])}>
                        {t('appstore.wizard.addTeam')}
                    </Button>
                </Group>
            </Card>
            {teams.length === 0 && <Text size="sm" c="dimmed">{t('appstore.wizard.noTeams')}</Text>}
            {teams.map((tm, i) => (
                <Card key={i} withBorder>
                    <Group align="flex-start" wrap="nowrap">
                        <TextInput w={180} label={t('appstore.wizard.teamName')} value={tm.name} onChange={(e) => update(i, { name: e.currentTarget.value })} />
                        <MultiSelect style={{ flexGrow: 1 }} label={t('appstore.wizard.members')} searchable
                            data={[...tm.emails, ...unassigned]} value={tm.emails} onChange={(emails) => update(i, { emails })} />
                        <ActionIcon mt={26} variant="subtle" color="red" onClick={() => setTeams(teams.filter((_, j) => j !== i))}
                            aria-label={t('appstore.wizard.removeTeam')}>
                            <Trash2 size={16} />
                        </ActionIcon>
                    </Group>
                </Card>
            ))}
            {teams.length > 0 && unassigned.length > 0 && (
                <Text size="sm" c="dimmed">{t('appstore.wizard.unassigned', { count: unassigned.length, emails: unassigned.join(', ') })}</Text>
            )}
            {problems.map(p => (
                <Alert key={p.kind} color="red" p="xs">
                    {t(`appstore.wizard.problem.${p.kind}`, { names: (p.names ?? []).join(', '), emails: (p.emails ?? []).join(', ') })}
                </Alert>
            ))}
        </Stack>
    );
}

// ── 3. Variables ────────────────────────────────────────────────────────

/**
 * The app's variables, grouped by where they go (Terraform, or the Packer
 * image of each template); a variable scoped per team or per member gets one
 * input per slot. Marker hints (`@openstack:...`) are stripped from descriptions.
 */
export function StepVariables({ state, set, variables, variablesQuery }) {
    const { t } = useTranslation();
    const multi = isMultiImage(variables);
    const setValue = (key, val) => set({ values: { ...state.values, [key]: val } });
    const setSlot = (key, slot, val) => set({ values: { ...state.values, [key]: { ...(state.values[key] ?? {}), [slot]: val } } });
    const networkVar = variables.find(v => v.osType === 'network' && v.osMode === 'id');
    const networkId = networkVar ? state.values[formKey(networkVar, multi)] : null;

    const groups = useMemo(() => {
        const out = new Map();
        for (const v of variables) {
            const g = v.source === 'packer' ? `packer:${v.template_key ?? 'default'}` : 'terraform';
            if (!out.has(g)) out.set(g, []);
            out.get(g).push(v);
        }
        return [...out.entries()];
    }, [variables]);

    if (variablesQuery.isPending) return <Text c="dimmed">{t('appstore.wizard.loadingVariables')}</Text>;
    if (variablesQuery.isError) return <Alert color="red">{variablesQuery.error.message}</Alert>;
    if (!variables.length) return <Alert color="gray">{t('appstore.wizard.noVariables')}</Alert>;

    const clean = (d) => String(d ?? '').replace(/@(openstack|platform):\S*/g, '').trim();

    return (
        <Accordion multiple defaultValue={groups.map(([g]) => g)} variant="separated">
            {groups.map(([group, vars]) => (
                <Accordion.Item key={group} value={group}>
                    <Accordion.Control>
                        {group === 'terraform'
                            ? t('appstore.wizard.groupTerraform')
                            : t('appstore.wizard.groupPacker', { template: group.split(':')[1] })}
                    </Accordion.Control>
                    <Accordion.Panel>
                        <Stack gap="lg">
                            {vars.map(v => {
                                const key = formKey(v, multi);
                                const scope = scopeOf(v);
                                const label = (
                                    <Group gap={6} component="span">
                                        <span>{v.name}</span>
                                        {v.required && <Text span c="red">*</Text>}
                                        {scope !== 'all' && <Badge size="xs" variant="light">{t(`appstore.wizard.scope.${scope}`)}</Badge>}
                                    </Group>
                                );
                                const common = { variable: v, credentialId: state.credentialId, networkId };
                                return (
                                    <Stack key={key} gap={4}>
                                        <MarkerError variable={v} />
                                        {clean(v.description) && <Text size="xs" c="dimmed">{clean(v.description)}</Text>}
                                        {scope === 'all' ? (
                                            isFileVar(v)
                                                ? <FileField {...common} label={label} value={state.values[key]?.all} onChange={(f) => setSlot(key, 'all', f)} />
                                                : <ValueField {...common} label={label} value={state.values[key]} onChange={(x) => setValue(key, x)} />
                                        ) : (
                                            <Stack gap={4}>
                                                <Text size="sm" fw={500}>{label}</Text>
                                                {slotKeys(v, state.teams).length === 0 && <Text size="xs" c="orange">{t('appstore.wizard.needsTeams')}</Text>}
                                                {slotKeys(v, state.teams).map(slot => (
                                                    isFileVar(v)
                                                        ? <FileField key={slot} {...common} label={slot} value={state.values[key]?.[slot]} onChange={(f) => setSlot(key, slot, f)} />
                                                        : <ValueField key={slot} {...common} label={slot} value={state.values[key]?.[slot] ?? ''} onChange={(x) => setSlot(key, slot, x)} />
                                                ))}
                                            </Stack>
                                        )}
                                    </Stack>
                                );
                            })}
                        </Stack>
                    </Accordion.Panel>
                </Accordion.Item>
            ))}
        </Accordion>
    );
}

/** Whether step 3 is done: no required input empty and no variable with a marker error. */
export function variablesComplete(state, variables) {
    return missingRequired(variables, state.values, state.teams).length === 0 && !variables.some(v => v.markerError);
}

// ── 4. Summary ──────────────────────────────────────────────────────────

/**
 * The chosen basics and teams, the values that will be sent (read from the
 * prepared request `body`, so defaults left alone do not appear), and what is
 * still missing.
 */
export function StepSummary({ state, app, credentials, courses, variables, body }) {
    const { t } = useTranslation();
    const credential = credentials.find(c => c.credentialId === state.credentialId);
    const course = courses.find(c => c.course === state.course);
    const missing = missingRequired(variables, state.values, state.teams);
    const tfEntries = Object.entries(body.userInputVar.terraform);
    const pkEntries = Object.entries(body.userInputVar.packer);
    const show = (v) => (typeof v === 'object' ? JSON.stringify(v) : String(v));

    return (
        <Stack gap="md">
            <Table variant="vertical" withTableBorder>
                <Table.Tbody>
                    <Table.Tr><Table.Th w={200}>{t('appstore.wizard.name')}</Table.Th><Table.Td>{state.name}</Table.Td></Table.Tr>
                    <Table.Tr><Table.Th>{t('appstore.wizard.app')}</Table.Th><Table.Td>{app?.name} <Code>{state.version}</Code></Table.Td></Table.Tr>
                    <Table.Tr><Table.Th>{t('appstore.wizard.credential')}</Table.Th><Table.Td>{credential?.project_name || credential?.project_id}</Table.Td></Table.Tr>
                    <Table.Tr><Table.Th>{t('appstore.wizard.course')}</Table.Th><Table.Td>{course?.display_name}</Table.Td></Table.Tr>
                    <Table.Tr>
                        <Table.Th>{t('appstore.wizard.teams')}</Table.Th>
                        <Table.Td>
                            {state.teams.length === 0
                                ? t('appstore.wizard.noTeamsShort')
                                : state.teams.map(tm => <div key={tm.name}><b>{tm.name}</b>: {tm.emails.join(', ') || '—'}</div>)}
                        </Table.Td>
                    </Table.Tr>
                </Table.Tbody>
            </Table>
            <Title order={5}>{t('appstore.wizard.values')}</Title>
            {tfEntries.length + pkEntries.length === 0 && <Text size="sm" c="dimmed">{t('appstore.wizard.allDefaults')}</Text>}
            {[...tfEntries.map(([k, v]) => ['terraform', k, v]), ...pkEntries.map(([k, v]) => ['packer', k, v])].map(([src, k, v]) => (
                <Text key={`${src}.${k}`} size="sm"><Code>{k}</Code> = {show(v)}</Text>
            ))}
            {body.files && Object.entries(body.files).map(([k, slots]) => (
                <Text key={`file.${k}`} size="sm"><Code>{k}</Code>: {Object.values(slots).map(f => f.name).join(', ')}</Text>
            ))}
            {missing.length > 0 && <Alert color="red">{t('appstore.wizard.missing', { names: missing.join(', ') })}</Alert>}
            {variables.length > 0 && <Text size="xs" c="dimmed">{t('appstore.wizard.defaultsNote')}</Text>}
        </Stack>
    );
}
