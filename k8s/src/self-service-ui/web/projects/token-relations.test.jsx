// @vitest-environment jsdom
import { describe, it, expect } from 'vitest';
import i18n from '/i18n/index.js';
import { splitRelation, relationLabel } from './token-labels.jsx';

// A relation token ("group:wwi23seb#dozent") is labelled from its group plus
// the role, so what matters is that the role comes off cleanly and reads in
// the UI's language — and that a role the UI has no text for still shows.
describe('relation tokens', () => {
    it('splits the role off a relation token', () => {
        expect(splitRelation('group:wwi23seb#dozent')).toEqual(['group:wwi23seb', 'dozent']);
        expect(splitRelation('group:wwi23seb')).toEqual(['group:wwi23seb', '']);
    });

    it('names known roles in the current language and passes unknown ones through', async () => {
        await i18n.changeLanguage('de');
        expect(relationLabel(i18n.t, 'dozent')).toBe('Dozent:in');
        await i18n.changeLanguage('en');
        expect(relationLabel(i18n.t, 'dozent')).toBe('Lecturer');
        expect(relationLabel(i18n.t, 'tutor')).toBe('tutor');
    });
});
