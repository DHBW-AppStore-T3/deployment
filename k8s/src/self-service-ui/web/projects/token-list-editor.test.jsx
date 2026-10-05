// @vitest-environment jsdom
import { describe, it, expect, afterEach, vi } from 'vitest';
import { cleanup, fireEvent, screen } from '@testing-library/react';
import '/test/jsdom-stubs.js';
import { renderView } from '/test/projects-harness.jsx';
import { TokenListEditor } from './component-token-list-editor.jsx';

// A bare email typed into a token field must be stored as a user: token. The
// badge strips the prefix for display, so the unprefixed form would look
// identical in the UI — and silently never match anyone's tokens.

function renderEditor(props) {
    return renderView(<TokenListEditor label="Can request" tokens={[]} onChange={() => {}} {...props} />);
}

const addDraft = (draft) => {
    fireEvent.change(screen.getByRole('combobox'), { target: { value: draft } });
    fireEvent.click(screen.getByRole('button', { name: 'Add' }));
};

describe('TokenListEditor', () => {
    afterEach(cleanup);

    it('normalizes a bare email to a user: token', () => {
        const onChange = vi.fn();
        renderEditor({ onChange });

        addDraft('nils.model@dhbw.de');

        expect(onChange).toHaveBeenCalledWith(['user:nils.model@dhbw.de']);
    });

    it('leaves prefixed tokens and group names alone', () => {
        const onChange = vi.fn();
        renderEditor({ onChange });

        addDraft('group:leiter-zwr');
        addDraft('user:someone@dhbw.de');

        expect(onChange).toHaveBeenNthCalledWith(1, ['group:leiter-zwr']);
        expect(onChange).toHaveBeenNthCalledWith(2, ['user:someone@dhbw.de']);
    });
});
