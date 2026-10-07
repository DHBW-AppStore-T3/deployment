import { useState } from 'react';
import { ActionIcon, Anchor, Code, Group, Stack, Table, Text, Tooltip } from '@mantine/core';
import { Eye, EyeOff } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { CopyableText } from '/helper/copyable-text.jsx';
import { ExternalLink } from '/helper/external-link.jsx';

// One person's access to one environment, as an app's outputs describe it:
// `user_accounts` (their account) and `team_vms` (their team's machine). The
// shapes are the app contract (appstore-api README, "App contract"):
//
//   user_accounts: { "<team>-<account>": { username, auth, type, ip, port } }
//   team_vms:      { "<team>": { code_server_url | url, floating_ip, fixed_ip, instance_name } }
//
// `type` says what `auth` is: a password, an SSH key, a login URL, or nothing.
// This is where the access data lives since mails no longer carry it (E5), so
// it is shown only here, to the person it belongs to, and a password stays
// hidden until asked for.

const str = (v) => (v === undefined || v === null ? '' : String(v));

/**
 * Show one person's access: a table per team VM (URL, public IP, instance) and
 * one per user account. Used by "Meine Zugänge" and the deployment detail view.
 */
export function AccessView({ userAccounts, teamVms }) {
    const { t } = useTranslation();
    const accounts = Object.values(userAccounts ?? {});
    const vms = Object.values(teamVms ?? {});

    if (!accounts.length && !vms.length) {
        return <Text size="sm" c="dimmed">{t('appstore.access.none')}</Text>;
    }

    return (
        <Stack gap="xs">
            {vms.map((vm, i) => {
                const url = str(vm.code_server_url || vm.url);
                return (
                    <Table key={`vm-${i}`} variant="vertical" withTableBorder layout="fixed">
                        <Table.Tbody>
                            {url && <Row label={t('appstore.access.url')}><ExternalLink href={url}>{url}</ExternalLink></Row>}
                            {vm.floating_ip && <Row label={t('appstore.access.publicIp')}><CopyableText value={str(vm.floating_ip)}><Code>{str(vm.floating_ip)}</Code></CopyableText></Row>}
                            {vm.instance_name && <Row label={t('appstore.access.instance')}><Code>{str(vm.instance_name)}</Code></Row>}
                        </Table.Tbody>
                    </Table>
                );
            })}
            {/* An account's link is not repeated when the team's table above already shows it. */}
            {accounts.map((a, i) => <Account key={`acc-${i}`} account={a} sharedUrl={vms.some(vm => str(vm.code_server_url || vm.url) === str(a.url))} />)}
        </Stack>
    );
}

/**
 * One user account: host, username and the `auth` shown according to its
 * `type`. An unknown type is treated as a password, so it stays hidden.
 */
function Account({ account, sharedUrl = false }) {
    const { t } = useTranslation();
    const type = ['password', 'ssh_key', 'oauth', 'none'].includes(account.type) ? account.type : 'password';
    // Apps that run as pods are reached by an https link, not by host and port.
    const host = !account.url && account.ip ? `${account.ip}${account.port ? `:${account.port}` : ''}` : '';

    return (
        <Table variant="vertical" withTableBorder layout="fixed">
            <Table.Tbody>
                {account.url && !sharedUrl && <Row label={t('appstore.access.url')}><ExternalLink href={str(account.url)}>{str(account.url)}</ExternalLink></Row>}
                {host && <Row label={t('appstore.access.host')}><CopyableText value={host}><Code>{host}</Code></CopyableText></Row>}
                {account.username && (
                    <Row label={t('appstore.access.username')}>
                        <CopyableText value={str(account.username)}><Code>{str(account.username)}</Code></CopyableText>
                    </Row>
                )}
                {type === 'password' && account.auth && (
                    <Row label={t('appstore.access.password')}><Secret value={str(account.auth)} /></Row>
                )}
                {type === 'ssh_key' && account.auth && (
                    <Row label={t('appstore.access.sshKey')}>
                        <CopyableText value={str(account.auth)}><Code block style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>{str(account.auth)}</Code></CopyableText>
                    </Row>
                )}
                {type === 'oauth' && account.auth && (
                    <Row label={t('appstore.access.login')}><Anchor href={str(account.auth)} target="_blank" rel="noopener noreferrer">{t('appstore.access.loginLink')}</Anchor></Row>
                )}
                {type === 'none' && <Row label={t('appstore.access.auth')}>{t('appstore.access.open')}</Row>}
            </Table.Tbody>
        </Table>
    );
}

/** A password, masked until the eye toggle is clicked; copyable either way. */
function Secret({ value }) {
    const { t } = useTranslation();
    const [shown, setShown] = useState(false);
    return (
        <Group gap="xs" wrap="nowrap">
            <CopyableText value={value}><Code>{shown ? value : '•'.repeat(Math.min(value.length, 12))}</Code></CopyableText>
            <Tooltip label={shown ? t('appstore.access.hide') : t('appstore.access.show')}>
                <ActionIcon variant="subtle" size="sm" onClick={() => setShown(s => !s)} aria-label={shown ? t('appstore.access.hide') : t('appstore.access.show')}>
                    {shown ? <EyeOff size={14} /> : <Eye size={14} />}
                </ActionIcon>
            </Tooltip>
        </Group>
    );
}

/** One label/value row of a vertical table. */
function Row({ label, children }) {
    return (
        <Table.Tr>
            <Table.Th w={160}>{label}</Table.Th>
            <Table.Td>{children}</Table.Td>
        </Table.Tr>
    );
}
