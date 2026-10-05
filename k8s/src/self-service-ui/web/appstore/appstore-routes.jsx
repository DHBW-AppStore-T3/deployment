// Route table of the AppStore section. Mounted lazily under /appstore by
// web/index.jsx when features.appStoreEnabled is set.
import { lazy, Suspense } from 'react';
import { Redirect, Route, Switch } from 'wouter';
import { useTranslation } from 'react-i18next';
import { Catalog } from '/appstore/catalog.jsx';
import { AppDetail } from '/appstore/app-detail.jsx';
import { RegisterApp } from '/appstore/register-app.jsx';
import { DeployWizard } from '/appstore/wizard/deploy-wizard.jsx';
import { Deployments } from '/appstore/deployments.jsx';
import { DeploymentDetail } from '/appstore/deployment-detail.jsx';
import { MyAccess } from '/appstore/my-access.jsx';
import { Credentials } from '/appstore/credentials.jsx';
import { AdminApprovals } from '/appstore/admin-approvals.jsx';

// Swagger UI is ~1 MB — only when the API documentation is opened.
const AppStoreApiSwagger = lazy(() =>
    import('/swagger/swagger.jsx').then(m => ({ default: m.AppStoreApiSwagger })));

/**
 * The AppStore section, under /appstore (paths here are relative to it; `/`
 * redirects to the catalogue). Two of these paths are part of the API's
 * contract: its mails link to /appstore/my-access and /appstore/deployments/<id>
 * (appstore-api, services/deployment_notifier.py).
 */
export function AppStore() {
    const { t } = useTranslation();
    return (
        <Suspense fallback={<div style={{ padding: '2rem' }}>{t('appstore.common.loading')}</div>}>
            <Switch>
                <Route path="/catalog" component={Catalog} />
                <Route path="/apps/new" component={RegisterApp} />
                <Route path="/apps/:appId" component={AppDetail} />
                <Route path="/deploy/:appId" component={DeployWizard} />
                <Route path="/deployments" component={Deployments} />
                <Route path="/deployments/:deploymentId" component={DeploymentDetail} />
                <Route path="/my-access" component={MyAccess} />
                <Route path="/credentials" component={Credentials} />
                <Route path="/admin" component={AdminApprovals} />
                <Route path="/api-doc" component={AppStoreApiSwagger} />
                <Route path="/">
                    <Redirect to="/catalog" replace />
                </Route>
            </Switch>
        </Suspense>
    );
}
