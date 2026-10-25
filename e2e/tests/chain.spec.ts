import { expect, test, type Page } from '@playwright/test'
import { enableAdminView, runId, signIn, sweepStale, type Session } from './helpers'

/**
 * The whole chain, once for a pod app and once for a kubevirt-vm app, as people do it in the UI:
 *   admin registers the app, submits a version and approves it  ->  a teacher deploys it to one
 *   student  ->  the deployment is checked from the outside (API status, live view, the link)
 *   ->  everything is removed again, also when a step in between fails.
 *
 * Needs E2E_ADMIN_PASSWORD and E2E_DOZENT_PASSWORD. Only one Windows VM fits the cluster at a time:
 * set E2E_VM=0 to leave the VM chain out while a hand-made one is running.
 */

interface Chain {
  kind: 'pod' | 'vm'
  repo: string
  /** The tag to submit; the first (newest) row of the version table when empty. */
  version?: string
  /** What the link must answer before anyone has signed in. */
  linkStatus: number[]
  ready: { timeoutMs: number }
}

const CHAINS: Chain[] = [
  {
    kind: 'pod',
    repo: 'https://github.com/DHBW-AppStore-T3/template-app',
    linkStatus: [200, 301, 302, 401, 403],
    ready: { timeoutMs: 6 * 60_000 },
  },
  {
    kind: 'vm',
    repo: 'https://github.com/DHBW-AppStore-T3/Windows-Matlab-App',
    version: 'v2.1.0',
    linkStatus: [401], // the noVNC proxy asks for the generated password
    ready: { timeoutMs: 15 * 60_000 },
  },
]

for (const chain of CHAINS) {
  test.describe.serial(`chain: ${chain.kind} app`, () => {
    test.skip(chain.kind === 'vm' && process.env.E2E_VM === '0', 'E2E_VM=0')

    const appName = `e2e-${chain.kind}-${runId}`
    const deploymentName = `E2E-${chain.kind}-${runId}`
    let admin: Session
    let dozent: Session
    let appId = ''
    let deploymentId = ''

    test.beforeAll(async ({ browser }) => {
      admin = await signIn(browser, 'admin')
      dozent = await signIn(browser, 'dozent')
      await sweepStale(admin, dozent)
      await enableAdminView(admin.page)
    })

    test.afterAll(async () => {
      // Always clean up: the deployment first (it destroys the namespace), then the app.
      if (deploymentId && dozent) await removeDeployment(dozent, deploymentId).catch((e) => console.warn('cleanup deployment:', e))
      // The app may exist although the test stopped before it learned its id: find it by name.
      if (admin) {
        const apps = await admin.api<{ appId: string; name: string }[]>('/apps/?limit=200')
        appId ||= apps.body?.find((a) => a.name === appName)?.appId ?? ''
        if (appId) await removeApp(admin, appId).catch((e) => console.warn('cleanup app:', e))
      }
      await admin?.context.close()
      await dozent?.context.close()
    })

    test('the admin registers the app and gets its versions', async () => {
      const { page } = admin
      await page.goto('/apps/create')
      await page.getByPlaceholder('Name').fill(appName)
      await page.getByPlaceholder('https://github.com...').fill(chain.repo)
      await page.getByRole('button', { name: 'Hinzufügen' }).click()
      await expect(page).toHaveURL(/\/apps$/, { timeout: 30_000 })

      await page.getByPlaceholder(/Apps suchen/).fill(appName)
      await page.locator('div', { hasText: appName }).getByRole('button', { name: 'Details' }).first().click()
      await expect(page).toHaveURL(/\/apps\/[0-9a-f-]{36}$/)
      appId = page.url().split('/').pop() as string
      await page.getByRole('button', { name: 'App Store' }).click()
      await expect(page.getByText('Freigabe-Status der Versionen', { exact: false })).toBeVisible()
    })

    test('the admin submits a version and approves it', async () => {
      const { page } = admin
      await page.goto(`/apps/${appId}`)
      await page.getByRole('button', { name: 'App Store' }).click()
      const row = chain.version
        ? page.getByRole('row').filter({ hasText: chain.version })
        : page.getByRole('row').filter({ hasText: 'Zur Prüfung einreichen' }).first()
      await row.getByText('Zur Prüfung einreichen').click()
      await page.getByRole('button', { name: 'Einreichen', exact: true }).click()
      await expect(page.getByText('Wartet auf Freigabe').first()).toBeVisible()

      await page.goto('/admin/apps')
      await page.getByText(appName, { exact: true }).click()
      await page.getByRole('button', { name: 'Genehmigen' }).click()
      await expect(page.getByText('Veröffentlicht').first()).toBeVisible()
    })

    test('the teacher deploys it to one student', async () => {
      const { page } = dozent
      await page.goto('/apps')
      await page.getByPlaceholder(/Apps suchen/).fill(appName)
      await page.locator('div', { hasText: appName }).getByRole('button', { name: 'Details' }).first().click()
      await page.getByRole('button', { name: 'Jetzt Deployen' }).click()

      await page.getByPlaceholder(/Pentesting|Name/).first().fill(deploymentName)
      await page.getByRole('button', { name: 'Studenten auswählen' }).click()
      await page.getByPlaceholder('Suche...').fill('student1')
      await page.getByText('Studentin Eins').first().click()
      await page.getByRole('button', { name: 'Weiter' }).click() // -> Verteilung
      await expect(page.getByRole('button', { name: 'Jeder Nutzer einzeln' })).toBeVisible()
      // "Jeder Nutzer einzeln" gives every person a team of their own: deterministic for one student
      // (an app that forces this mode has the button locked already).
      const perPerson = page.getByRole('button', { name: 'Jeder Nutzer einzeln' })
      if (await perPerson.isEnabled()) await perPerson.click()
      await expect(page.getByText(/1\s*\/\s*1\s*zugewiesen/)).toBeVisible()
      await page.getByRole('button', { name: 'Weiter' }).click() // -> Variablen
      await expect(page.getByRole('heading', { name: 'Variablen-Konfiguration' })).toBeVisible()

      if (chain.kind === 'vm') await smallestVm(page)
      await page.getByRole('button', { name: 'Weiter' }).click() // -> Übersicht
      // Each step is waited for before the next click: a click on a step that is still changing is lost.
      await page.getByRole('button', { name: 'Deployen', exact: true }).click()

      // The app returns to the list; the id comes from the API, by the name this run gave it.
      await expect(page).toHaveURL(/\/deployments$/, { timeout: 60_000 })
      await expect
        .poll(
          async () => {
            const list = await dozent.api<{ deploymentId: string; name: string }[]>('/deployments/')
            deploymentId = list.body?.find((d) => d.name === deploymentName)?.deploymentId ?? ''
            return deploymentId
          },
          { timeout: 60_000, message: 'the new deployment is not in the list' },
        )
        .not.toBe('')
    })

    test('it runs, and the link answers', async () => {
      await expect
        .poll(async () => (await dozent.api<{ status: string }>(`/deployments/${deploymentId}`)).body.status, {
          timeout: chain.ready.timeoutMs,
          intervals: [10_000],
          message: 'the deployment never reached success',
        })
        .toBe('success')

      const live = await dozent.api<{ workloads: { ready: boolean; url: string | null }[] }>(
        `/deployments/${deploymentId}/resources`,
      )
      expect(live.status).toBe(200)
      expect(live.body.workloads.length).toBeGreaterThan(0)
      expect(live.body.workloads.every((w) => w.ready)).toBe(true)

      const url = live.body.workloads[0].url
      expect(url, 'the live view carries the link').toBeTruthy()
      const answer = await dozent.page.request.get(url as string, { maxRedirects: 0 })
      expect(chain.linkStatus, `the link answered ${answer.status()}`).toContain(answer.status())
    })

    test('the detail page shows the right runtime', async () => {
      await dozent.page.goto(`/deployments/${deploymentId}`)
      await expect(dozent.page.getByTestId('deployment-runtime')).toHaveText(
        chain.kind === 'vm' ? 'VM im Cluster' : 'Pods im Cluster',
      )
    })
  })
}

/** Drag the vCPU and RAM sliders of the wizard to their lowest value (the VM boots on less, and the step is exercised). */
async function smallestVm(page: Page): Promise<void> {
  const picker = page.getByTestId('resource-picker')
  await expect(picker).toBeVisible()
  const [cpu, memory] = [picker.getByRole('slider').nth(0), picker.getByRole('slider').nth(1)]
  await cpu.focus()
  await page.keyboard.press('Home')
  await memory.focus()
  await page.keyboard.press('Home')
  await expect(picker.getByTestId('cpu-vm')).toContainText('2')
}

/** Delete it the way a person does (the page's own buttons), then wait until the API no longer knows it. */
async function removeDeployment(session: Session, id: string): Promise<void> {
  const { page } = session
  await page.goto(`/deployments/${id}`)
  await page.getByTestId('btn-delete-deployment').click()
  await page.getByTestId('btn-confirm-delete').click()
  await expect
    .poll(async () => (await session.api(`/deployments/${id}`)).status, { timeout: 5 * 60_000, intervals: [5_000] })
    .toBe(404)
}

async function removeApp(admin: Session, id: string): Promise<void> {
  const status = await admin.remove(`/apps/${id}`)
  expect([200, 204, 404], `deleting the app answered ${status}`).toContain(status)
}
