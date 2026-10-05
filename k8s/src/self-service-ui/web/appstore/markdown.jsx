// Markdown rendering for app descriptions and release notes (app-detail.jsx),
// sanitised because app authors are not trusted.
import { useMemo } from 'react';
import { Typography } from '@mantine/core';
import { marked } from 'marked';
import DOMPurify from 'dompurify';

// App descriptions and release notes are Markdown written by app authors, so
// untrusted: the HTML marked produces goes through DOMPurify before React sees
// it, and links open in a new tab without handing over the opener.
DOMPurify.addHook('afterSanitizeAttributes', (node) => {
    if (node.tagName === 'A') {
        node.setAttribute('target', '_blank');
        node.setAttribute('rel', 'noopener noreferrer');
    }
});

/** Render Markdown (GFM) to an HTML string that has been sanitised by DOMPurify. */
export function renderMarkdown(source) {
    const html = marked.parse(String(source ?? ''), { async: false, gfm: true, breaks: false });
    return DOMPurify.sanitize(html, { USE_PROFILES: { html: true } });
}

/** Show `source` as sanitised Markdown with Mantine typography; renders nothing for an empty source. */
export function Markdown({ source }) {
    const html = useMemo(() => renderMarkdown(source), [source]);
    if (!source) return null;
    return (
        <Typography>
            <div dangerouslySetInnerHTML={{ __html: html }} />
        </Typography>
    );
}
