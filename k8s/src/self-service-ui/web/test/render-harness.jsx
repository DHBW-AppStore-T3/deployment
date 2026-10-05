import { render } from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import './jsdom-stubs.js';
// Initialises i18next once for every test: a component calling t() without it
// renders bare keys, which would pass a smoke test and fail in the browser.
import '/i18n/index.js';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AuthContext } from '/providers/auth.jsx';
import { ConfirmProvider } from '/providers/confirm.jsx';
import { ErrorModalProvider } from '/providers/error-modal.jsx';

// The scaffolding a view needs to render at all: the providers it reads from,
// and a query client that fails fast.
//
// Deliberately thin. This is not a place to assert what a view LOOKS like —
// that would freeze the markup and make every layout change a test change. It
// answers one question: does this thing render without throwing. Both of the
// releases that broke on 2026-08-25 failed exactly that question while lint,
// the unit tests and the build were all green.

// retry: false — a test must not sit through three backoffs for a mock that was
// always going to reject. gcTime: Infinity keeps the cache from being collected
// mid-assertion.
export function testQueryClient() {
    return new QueryClient({
        defaultOptions: {
            queries: { retry: false, gcTime: Infinity },
            mutations: { retry: false },
        },
        // The default logger prints every rejected query; a test that EXPECTS a
        // failure would then bury the real output.
        logger: { log: () => {}, warn: () => {}, error: () => {} },
    });
}

const USER = { profile: { email: 'dennis.pfisterer@dhbw.de', name: 'Test User' }, access_token: 't' };

// renderWithProviders is the harness every area uses: the providers a view
// reads from, nothing area-specific. An area that needs a context of its own
// wraps `ui` in it (see projects-harness.jsx for the Cloud Projects config).
export function renderWithProviders(ui, { user = USER } = {}) {
    const client = testQueryClient();
    const result = render(
        <MantineProvider>
            <QueryClientProvider client={client}>
                <AuthContext.Provider value={{ user, loading: false }}>
                    <ErrorModalProvider>
                        <ConfirmProvider>
                            {ui}
                        </ConfirmProvider>
                    </ErrorModalProvider>
                </AuthContext.Provider>
            </QueryClientProvider>
        </MantineProvider>,
    );
    return { ...result, client };
}
