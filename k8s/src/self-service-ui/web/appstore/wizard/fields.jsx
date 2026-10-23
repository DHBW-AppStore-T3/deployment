import { Alert, Anchor, Group, MultiSelect, NumberInput, Select, Stack, Switch, Text, Textarea, TextInput } from '@mantine/core';
import { Dropzone } from '@mantine/dropzone';
import { useQuery } from '@tanstack/react-query';
import { FileUp, X } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useAppStoreApi } from '/appstore/api-appstore.jsx';
import { appstoreKeys } from '/appstore/query-keys.js';
import { hasPicker, isBool, isEnumVar, isList, isNumber, readFile } from '/appstore/wizard-logic.js';

// The input for ONE value of a variable. Whether a variable needs one value or
// one per team/member is the step's business (StepVariables in steps.jsx); this picks
// the widget: a resource picker for @openstack markers, a switch, a number, a
// list, or text.

/** Per the API's limits (routers/deployments.py): 2 MiB per file. */
export const MAX_FILE_BYTES = 2 * 1024 * 1024;

/**
 * The input widget for one value of a non-file variable, chosen by marker and
 * HCL type. `networkId` narrows a subnet picker to that network.
 */
export function ValueField({ variable: v, value, onChange, credentialId, networkId, label, error }) {
    const { t } = useTranslation();
    if (isEnumVar(v)) {
        return <Select label={label} data={v.values} value={value ? String(value) : (v.default ?? null)} onChange={(x) => onChange(x ?? '')} error={error} allowDeselect={false} />;
    }
    if (hasPicker(v)) {
        return <ResourcePicker variable={v} value={value} onChange={onChange} credentialId={credentialId} networkId={networkId} label={label} error={error} />;
    }
    if (isBool(v.type)) {
        return <Switch label={label} checked={Boolean(value)} onChange={(e) => onChange(e.currentTarget.checked)} />;
    }
    if (isNumber(v.type)) {
        return <NumberInput label={label} value={value === '' ? '' : value} onChange={(x) => onChange(x === '' ? '' : x)} error={error} />;
    }
    if (isList(v.type)) {
        return <Textarea label={label} value={value ?? ''} onChange={(e) => onChange(e.currentTarget.value)} autosize minRows={2}
            placeholder={t('appstore.wizard.listPlaceholder')} error={error} />;
    }
    return <TextInput label={label} value={value ?? ''} onChange={(e) => onChange(e.currentTarget.value)} error={error}
        placeholder={v.default !== undefined && v.default !== null ? String(v.default) : undefined} />;
}

/**
 * Offer what the chosen credential's project has, for an
 * `@openstack:<kind>[:id|name][:multi]` marker (api.listResources). It stores
 * the id or the name, whichever the marker asks for. If OpenStack does not
 * answer, a text field takes over: the value can still be typed in.
 */
function ResourcePicker({ variable: v, value, onChange, credentialId, networkId, label, error }) {
    const { t } = useTranslation();
    const api = useAppStoreApi();
    const kind = v.osType;
    const filter = kind === 'subnet' && networkId ? { network_id: networkId } : undefined;
    const query = useQuery({
        queryKey: appstoreKeys.resources(credentialId, kind, filter?.network_id),
        queryFn: () => api.listResources(credentialId, kind, filter),
        enabled: Boolean(credentialId),
        staleTime: 60_000,
    });
    const byName = (v.osMode || 'name') === 'name';
    const multi = Boolean(v.osMulti) || isList(v.type);

    if (query.isError) {
        return (
            <>
                <TextInput label={label} value={Array.isArray(value) ? value.join(', ') : value ?? ''} error={error}
                    onChange={(e) => onChange(multi ? e.currentTarget.value.split(',').map(s => s.trim()).filter(Boolean) : e.currentTarget.value)} />
                <Text size="xs" c="orange">{t('appstore.wizard.pickerUnavailable')}</Text>
            </>
        );
    }

    const seen = new Set();
    const data = (query.data ?? []).map(item => {
        const val = String((byName ? item.name : item.id) ?? '');
        const extra = kind === 'flavor' ? ` · ${item.vcpus} vCPU, ${Math.round((item.ram ?? 0) / 1024)} GB` : '';
        return { value: val, label: `${item.name || item.id}${extra}${byName ? '' : ` (${String(item.id).slice(0, 8)})`}` };
    }).filter(o => o.value && !seen.has(o.value) && seen.add(o.value));

    // A value the list does not know (typed earlier, or from a default) stays selectable.
    for (const x of (Array.isArray(value) ? value : [value]).filter(Boolean)) {
        if (!seen.has(String(x))) data.push({ value: String(x), label: String(x) });
    }

    const common = { label, data, searchable: true, error, nothingFoundMessage: t('appstore.wizard.nothingFound'), disabled: !credentialId || query.isPending };
    // The API caches the lists for a while; this drops that cache for the
    // kind, for a resource just created in Horizon.
    const reload = async () => {
        await api.refreshResources(credentialId, kind);
        await query.refetch();
    };
    return (
        <Stack gap={2}>
            {multi
                ? <MultiSelect {...common} value={Array.isArray(value) ? value.map(String) : []} onChange={onChange} clearable />
                : <Select {...common} value={value ? String(value) : null} onChange={(x) => onChange(x ?? '')} clearable />}
            {credentialId && (
                <Anchor component="button" type="button" size="xs" onClick={reload} disabled={query.isFetching} ta="left">
                    {t('appstore.wizard.reloadList')}
                </Anchor>
            )}
        </Stack>
    );
}

/**
 * Take one upload for a `@openstack:file:<scope>:<ext>` marker. The bytes
 * travel base64 in the deploy request and end up on the VM through cloud-init.
 * `value` is readFile()'s result, or empty.
 */
export function FileField({ variable: v, value, onChange, label }) {
    const { t } = useTranslation();
    const accept = (v.fileExtensions ?? []).map(e => `.${e}`);
    return (
        <div>
            <Text size="sm" fw={500} mb={4}>{label}</Text>
            {value?.content_b64 ? (
                <Group justify="space-between" p="xs" style={{ border: '1px solid var(--mantine-color-gray-3)', borderRadius: 4 }}>
                    <Text size="sm">{value.name} ({Math.ceil(value.size / 1024)} KB)</Text>
                    <X size={16} style={{ cursor: 'pointer' }} onClick={() => onChange(null)} aria-label={t('appstore.wizard.removeFile')} />
                </Group>
            ) : (
                <Dropzone
                    onDrop={async (files) => onChange(await readFile(files[0]))}
                    maxFiles={1}
                    maxSize={MAX_FILE_BYTES}
                    accept={accept.length ? { 'application/octet-stream': accept } : undefined}
                    p="md"
                >
                    <Group gap="xs" justify="center" style={{ pointerEvents: 'none' }}>
                        <FileUp size={18} />
                        <Text size="sm">{t('appstore.wizard.dropFile', { types: accept.join(', ') || t('appstore.wizard.anyType') })}</Text>
                    </Group>
                </Dropzone>
            )}
        </div>
    );
}

/** The API's complaint about a malformed @openstack marker on this variable, if any. */
export function MarkerError({ variable }) {
    if (!variable.markerError) return null;
    const e = variable.markerError;
    return <Alert color="red" p="xs">{`${e.variable ?? variable.name}${e.location ? ` (${e.location})` : ''}: ${e.message}`}</Alert>;
}
