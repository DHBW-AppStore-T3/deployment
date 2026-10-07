// The deploy wizard page (/appstore/deploy/:appId[?version=<tag>]): holds the
// wizard state and loads its data; steps.jsx renders the steps, wizard-logic.js
// holds the rules.
import { useMemo, useState } from 'react';
import { Alert, Anchor, Button, Container, Group, Stack, Stepper, Title } from '@mantine/core';
import { useQuery } from '@tanstack/react-query';
import { ArrowLeft, Rocket } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Link, useLocation, useSearch } from 'wouter';
import { useAppStoreApi } from '/appstore/api-appstore.jsx';
import { appstoreKeys } from '/appstore/query-keys.js';
import { useMe } from '/appstore/use-appstore.jsx';
import { basicsComplete, StepBasics, StepSummary, StepTeams, StepVariables, variablesComplete } from '/appstore/wizard/steps.jsx';
import { buildDeployment, dedupe, effectiveValues, teamProblems } from '/appstore/wizard-logic.js';
import { LoadError, Loading, useApiMutation } from '/helper/query-state.jsx';

// One empty list for every "not loaded yet", so memos depending on it stay put.
const NONE = [];

/**
 * Deploying an app for a course: what (app and version), where (the OpenStack
 * project of one of the caller's credentials), for whom (the course and its
 * teams), how (the app's variables), then a summary. The API checks all of it
 * again: the version's approval for its commit, the course, every team member
 * against the course's students. On success it navigates to the new deployment.
 */
export function DeployWizard({ params }) {
    const { t } = useTranslation();
    const api = useAppStoreApi();
    const [, navigate] = useLocation();
    const search = useSearch();
    const { canDeploy, query: meQuery } = useMe();
    const appId = params.appId;
    const [step, setStep] = useState(0);
    const [state, setState] = useState(() => ({
        name: '', version: new URLSearchParams(search).get('version'), credentialId: null, course: null, teams: [], values: {},
    }));
    const set = (patch) => setState(s => ({ ...s, ...patch }));

    const appQuery = useQuery({ queryKey: appstoreKeys.app(appId), queryFn: () => api.getApp(appId) });
    const credentialsQuery = useQuery({ queryKey: appstoreKeys.credentials(), queryFn: api.listCredentials });
    const coursesQuery = useQuery({ queryKey: appstoreKeys.courses(), queryFn: api.listMyCourses });
    const app = appQuery.data;
    const versions = useMemo(
        () => (app?.versions ?? NONE).filter(v => v.approved || app?.is_private),
        [app],
    );
    const credentials = credentialsQuery.data ?? NONE;
    const courses = coursesQuery.data ?? NONE;
    // The version and course in effect: chosen, or the only/newest one.
    const version = state.version ?? versions[0]?.version ?? null;
    const course = state.course ?? (courses.length === 1 ? courses[0].course : null);

    const studentsQuery = useQuery({
        queryKey: appstoreKeys.students(course),
        queryFn: () => api.listStudents(course),
        enabled: Boolean(course),
    });
    const variablesQuery = useQuery({
        queryKey: appstoreKeys.variables(appId, version),
        queryFn: () => api.getVariables(appId, version),
        enabled: Boolean(version),
    });

    const variables = useMemo(() => dedupe(variablesQuery.data), [variablesQuery.data]);
    // Apps with an appstore.yaml run as pods: no OpenStack credential, no VM settings.
    const runtimeQuery = useQuery({
        queryKey: appstoreKeys.runtime(appId, version),
        queryFn: () => api.getRuntime(appId, version),
        enabled: Boolean(version),
    });
    const pods = runtimeQuery.data?.runtime === 'kubernetes';

    // What the steps show: first choices where nothing was chosen yet (the
    // newest deployable version, the only credential, the only course), and
    // the variables' defaults under what was entered. Derived, not stored:
    // `state` holds only what the person entered.
    const view = useMemo(() => ({
        ...state,
        version: state.version ?? versions[0]?.version ?? null,
        credentialId: state.credentialId ?? (credentials.length === 1 ? credentials[0].credentialId : null),
        course: state.course ?? (courses.length === 1 ? courses[0].course : null),
        values: effectiveValues(variables, state.values, state.teams),
    }), [state, versions, credentials, courses, variables]);

    const body = useMemo(() => buildDeployment({
        name: view.name, appId, releaseTag: view.version, course: view.course, credentialId: pods ? null : view.credentialId,
        teams: view.teams, variables, values: view.values,
    }), [view, appId, variables, pods]);

    const create = useApiMutation({
        mutationFn: () => api.createDeployment(body),
        invalidates: [appstoreKeys.deployments(), appstoreKeys.credentials()],
        onSuccess: (dep) => navigate(`/deployments/${dep.deploymentId}`),
        reportErrors: 'inline',
    });

    if (meQuery.isSuccess && !canDeploy) {
        return <Container py="xl"><Alert color="yellow">{t('appstore.wizard.notAllowed')}</Alert></Container>;
    }
    if (appQuery.isPending) return <Container py="xl"><Loading /></Container>;
    if (appQuery.isError) return <Container py="xl"><LoadError query={appQuery} /></Container>;

    const stepOk = [
        basicsComplete(view, pods),
        teamProblems(view.teams).length === 0,
        variablesComplete(view, variables),
        true,
    ];
    const last = 3;

    return (
        <Container size="lg" py="xl">
            <Stack gap="md">
                <Anchor component={Link} href={`/apps/${appId}`} size="sm"><Group gap={4}><ArrowLeft size={14} />{app.name}</Group></Anchor>
                <Title order={2}>{t('appstore.wizard.title', { app: app.name })}</Title>
                {versions.length === 0 && <Alert color="yellow">{t('appstore.appDetail.noApprovedVersion')}</Alert>}
                <Stepper active={step} onStepClick={(i) => (i < step || stepOk.slice(0, i).every(Boolean)) && setStep(i)}>
                    <Stepper.Step label={t('appstore.wizard.stepBasics')}>
                        <StepBasics state={view} set={set} app={app} versions={versions} credentials={credentials} courses={courses} pods={pods} />
                    </Stepper.Step>
                    <Stepper.Step label={t('appstore.wizard.stepTeams')}>
                        <StepTeams state={view} set={set} students={studentsQuery.data ?? NONE} studentsQuery={studentsQuery} />
                    </Stepper.Step>
                    <Stepper.Step label={t('appstore.wizard.stepVariables')}>
                        <StepVariables state={view} set={set} variables={variables} variablesQuery={variablesQuery} />
                    </Stepper.Step>
                    <Stepper.Step label={t('appstore.wizard.stepSummary')}>
                        <StepSummary state={view} app={app} credentials={credentials} courses={courses} variables={variables} body={body} pods={pods} />
                    </Stepper.Step>
                </Stepper>
                {create.error && <Alert color="red">{create.error.message}</Alert>}
                <Group justify="space-between">
                    <Button variant="default" disabled={step === 0} onClick={() => setStep(s => s - 1)}>{t('appstore.wizard.back')}</Button>
                    {step < last ? (
                        <Button disabled={!stepOk[step]} onClick={() => setStep(s => s + 1)}>{t('appstore.wizard.next')}</Button>
                    ) : (
                        <Button leftSection={<Rocket size={16} />} loading={create.isPending} disabled={!stepOk.every(Boolean)}
                            onClick={() => create.mutate()}>
                            {t('appstore.wizard.deploy')}
                        </Button>
                    )}
                </Group>
            </Stack>
        </Container>
    );
}
