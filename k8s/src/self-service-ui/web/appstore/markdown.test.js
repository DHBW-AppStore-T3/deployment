// @vitest-environment jsdom
import { describe, it, expect } from 'vitest';
import { renderMarkdown } from './markdown.jsx';

describe('app descriptions', () => {
    it('render Markdown and drop scripts and handlers', () => {
        const html = renderMarkdown('# Titel\n\n<script>alert(1)</script><img src=x onerror="alert(2)">\n\n[link](https://x.example)');
        expect(html).toContain('<h1');
        expect(html).not.toContain('<script');
        expect(html).not.toContain('onerror');
        expect(html).toContain('rel="noopener noreferrer"');
    });

    it('drop javascript: links', () => {
        expect(renderMarkdown('[x](javascript:alert(1))')).not.toContain('javascript:');
    });
});
