{{/* Base chart name */}}
{{- define "appstore.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end }}

{{/* Fully qualified release name */}}
{{- define "appstore.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end }}

{{/* Chart label */}}
{{- define "appstore.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end }}

{{/* Common labels, optionally scoped to a component */}}
{{- define "appstore.labels" -}}
app.kubernetes.io/name: {{ include "appstore.name" .context }}
helm.sh/chart: {{ include "appstore.chart" .context }}
app.kubernetes.io/instance: {{ .context.Release.Name }}
app.kubernetes.io/managed-by: {{ .context.Release.Service }}
{{- if .context.Chart.AppVersion }}
app.kubernetes.io/version: {{ .context.Chart.AppVersion | quote }}
{{- end }}
{{- if .component }}
app.kubernetes.io/component: {{ .component }}
{{- end }}
{{- end }}

{{/* Selector labels, optionally scoped to a component */}}
{{- define "appstore.selectorLabels" -}}
app.kubernetes.io/name: {{ include "appstore.name" .context }}
app.kubernetes.io/instance: {{ .context.Release.Name }}
{{- if .component }}
app.kubernetes.io/component: {{ .component }}
{{- end }}
{{- end }}

{{/* Component-scoped name */}}
{{- define "appstore.componentName" -}}
{{- $base := include "appstore.fullname" .context -}}
{{- if .component -}}
{{- printf "%s-%s" $base .component | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $base -}}
{{- end -}}
{{- end }}

{{/* The Secret both components read: the chart's own, or existingSecret */}}
{{- define "appstore.secretName" -}}
{{- default (include "appstore.fullname" .) .Values.appstore.existingSecret -}}
{{- end }}

{{/* The API as the worker reaches it: OpenTofu's state backend lives there */}}
{{- define "appstore.apiUrl" -}}
{{- printf "http://%s:8000" (include "appstore.componentName" (dict "context" . "component" "api")) -}}
{{- end }}

{{/*
Restart the pods when the configuration changes: the values carry every
setting, the chart's own Secret included. A changed template arrives with a
new chart version, whose new image tag rolls the pods anyway.
*/}}
{{- define "appstore.rolloutAnnotations" -}}
checksum/values: {{ .Values | toJson | sha256sum }}
{{- end }}

{{/* Settings both processes read, from the Secret */}}
{{- define "appstore.sharedSecretEnv" -}}
- name: DATABASE_URL
  valueFrom:
    secretKeyRef:
      name: {{ include "appstore.secretName" . }}
      key: database-url
- name: CREDENTIAL_ENCRYPTION_KEY
  valueFrom:
    secretKeyRef:
      name: {{ include "appstore.secretName" . }}
      key: credential-encryption-key
- name: APP_GIT_ALLOWED_HOSTS
  value: {{ .Values.appstore.gitAllowedHosts | quote }}
{{- end }}

{{/* Hardened container defaults shared by both components */}}
{{- define "appstore.restrictedSecurityContext" -}}
runAsNonRoot: true
allowPrivilegeEscalation: false
readOnlyRootFilesystem: true
capabilities:
  drop: ["ALL"]
seccompProfile:
  type: RuntimeDefault
{{- end }}

{{/* Environment shared by API and worker for pod apps */}}
{{- define "appstore.podAppsEnv" -}}
{{- $p := .Values.appstore.podApps -}}
- name: K8S_ZONE
  value: {{ $p.zone | quote }}
- name: K8S_APP_DOMAIN
  value: {{ $p.appDomain | quote }}
- name: APP_IMAGE_REGISTRY_ALLOWLIST
  value: {{ $p.imageRegistryAllowlist | quote }}
- name: APP_MAX_CPU
  value: {{ $p.maxCpu | quote }}
- name: APP_MAX_MEMORY
  value: {{ $p.maxMemory | quote }}
- name: APP_MAX_STORAGE
  value: {{ $p.maxStorage | quote }}
{{- end }}

{{/* Cluster-scoped objects are shared by all installs in the cluster: name them per namespace */}}
{{- define "appstore.podAppsDeployerRole" -}}
{{- printf "appstore-%s-deployer" .Release.Namespace -}}
{{- end }}
