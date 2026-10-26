import { expect, type Browser, type BrowserContext, type Page } from '@playwright/test'

export type Role = 'admin' | 'dozent'

const USERS: Record<Role, { name: string; passwordEnv: string }> = {
  admin: { name: 'admin.demo', passwordEnv: 'E2E_ADMIN_PASSWORD' },
  dozent: { name: 'dozent.demo', passwordEnv: 'E2E_DOZENT_PASSWORD' },
}

/** A person signed in through Keycloak, with the bearer token the app uses so the test can ask the API. */
export interface Session {
  context: BrowserContext
  page: Page
  api: <T = unknown>(path: string) => Promise<{ status: number; body: T }>
  /** A write the page itself could make (the app's own "Löschen"), used to clean up. */
  remove: (path: string) => Promise<number>
}

export async function signIn(browser: Browser, role: Role): Promise<Session> {
  const password = process.env[USERS[role].passwordEnv]
  if (!password) throw new Error(`${USERS[role].passwordEnv} is not set`)
  const context = await browser.newContext()
  const page = await context.newPage()
  let token = ''
  let tokenSeen = 0
  page.on('request', (request) => {
    const header = request.headers()['authorization']
    if (header?.startsWith('Bearer ') && request.url().includes('/api/')) {
      token = header
      tokenSeen = Date.now()
    }
  })
  // Access tokens live a few minutes and a chain runs longer: when the last one is old, load a page
  // so the app renews it, and take the one its next API call carries.
  const fresh = async () => {
    if (token && Date.now() - tokenSeen < 2 * 60_000) return
    const before = tokenSeen
    await page.goto('/dashboard')
    await expect.poll(() => tokenSeen, { message: 'the app did not renew its token' }).toBeGreaterThan(before)
  }
  await page.goto('/')
  // The landing page offers the single sign-on first; with a live session it passes straight through.
  const start = page.getByRole('button', { name: /Mit DHBW anmelden/ }).or(page.getByRole('link', { name: /Mit DHBW anmelden/ }))
  await start.first().click({ timeout: 30_000 })
  await page.locator('#username').fill(USERS[role].name)
  await page.locator('#password').fill(password)
  await page.locator('#kc-login').click()
  await expect(page.getByRole('link', { name: 'Apps' }).first()).toBeVisible({ timeout: 60_000 })
  await expect.poll(() => token, { message: 'the app never called the API with a token' }).not.toBe('')

  const api = async <T,>(path: string) => {
    await fresh()
    const response = await page.request.get(`/api${path}`, { headers: { Authorization: token } })
    const text = await response.text()
    return { status: response.status(), body: (text ? JSON.parse(text) : null) as T }
  }
  const remove = async (path: string) => (await fresh(), await page.request.delete(`/api${path}`, { headers: { Authorization: token } })).status()
  return { context, page, api, remove }
}

/** Apps and deployments a failed earlier run left behind: everything named e2e-*, removed before a new chain starts. */
export async function sweepStale(admin: Session, teacher: Session): Promise<void> {
  // Deployments first, by their own name and with the eyes of the one who owns them (the teacher):
  // the list only shows a person's own, and the app they belong to may be gone already.
  for (const session of [teacher, admin]) {
    const deployments = await session.api<{ deploymentId: string; name: string }[]>('/deployments/')
    for (const d of deployments.body ?? []) if (d.name.startsWith('E2E-')) await session.remove(`/deployments/${d.deploymentId}`)
  }
  const apps = await admin.api<{ appId: string; name: string }[]>('/apps/?limit=200')
  for (const app of apps.body ?? []) if (app.name.startsWith('e2e-')) await admin.remove(`/apps/${app.appId}`)
}

/** Switch on the admin view (the app store tab and version management only exist there). */
export async function enableAdminView(page: Page): Promise<void> {
  await page.goto('/admin/settings')
  const toggle = page.getByRole('switch').first()
  if ((await toggle.getAttribute('aria-checked')) !== 'true') await toggle.click()
  await expect(toggle).toHaveAttribute('aria-checked', 'true')
}

export const runId = (process.env.GITHUB_RUN_ID ?? String(Date.now())).slice(-8)
