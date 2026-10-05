// @vitest-environment jsdom
import { describe, it, expect, afterEach } from 'vitest';
import { cleanup, fireEvent, screen } from '@testing-library/react';
import '/test/jsdom-stubs.js';
import { renderView } from '/test/projects-harness.jsx';
import { QuotaBadges } from './component-common.jsx';
import { BudgetFormModal } from './modal-budget-form.jsx';

const cores = { id: 'cores', name: 'Cores', group: 'Compute', min: 1, max: 64, default: 4 };
const ipv4 = { id: 'dhbw-ipv4', name: 'DHBW IPv4 network', kind: 'bool', group: 'Networks', min: 0, max: 0 };

describe('QuotaBadges', () => {
    afterEach(cleanup);

    // An availability is granted or not; "0 DHBW IPv4 network" reads like an amount.
    it('names a granted availability and leaves a withheld one out', () => {
        renderView(<QuotaBadges resources={[cores, ipv4]} quota={{ cores: 2, 'dhbw-ipv4': 0 }} />);
        expect(screen.getByText('2 Cores')).toBeTruthy();
        expect(screen.queryByText(/DHBW IPv4 network/)).toBeNull();

        cleanup();
        renderView(<QuotaBadges resources={[cores, ipv4]} quota={{ cores: 2, 'dhbw-ipv4': 1 }} />);
        expect(screen.getByText('DHBW IPv4 network')).toBeTruthy();
    });
});

describe('BudgetFormModal in request mode', () => {
    afterEach(cleanup);

    // Opened from the page header there is no parent in hand; what the form may
    // offer is what the budget picked under "Request from" carries.
    it('offers only what the chosen source budget carries', async () => {
        const source = {
            id: 'b_pool', kind: 'budget', status: 'approved', name: 'Pool',
            limit: { cores: 20 }, available_resources: ['cores'],
        };
        renderView(<BudgetFormModal opened onClose={() => {}} mode="request"
            resources={[cores, ipv4]} eligibleBudgets={[source]} />);
        fireEvent.click(await screen.findByRole('tab', { name: /Resources/ }));
        expect(screen.getAllByText(/Cores/).length).toBeGreaterThan(0);
        expect(screen.queryByText('DHBW IPv4 network')).toBeNull();
    });
});
