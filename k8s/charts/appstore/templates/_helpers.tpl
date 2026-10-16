{{/* Names: every object is <fullname>-<component>; cluster-wide ones carry the namespace too. */}}
{{- define "appstore.fullname" -}}
{{- default "appstore-t3" .Values.fullnameOverride | trunc 40 | trimSuffix "-" -}}
{{- end }}

{{- define "appstore.name" -}}
{{- printf "%s-%s" (include "appstore.fullname" .context) .component | trunc 63 | trimSuffix "-" -}}
{{- end }}

{{/* Cluster-scoped objects are shared by every installation in the cluster: name them per namespace. */}}
{{- define "appstore.clusterName" -}}
{{- printf "%s-%s-%s" (include "appstore.fullname" .context) .context.Release.Namespace .component | trunc 63 | trimSuffix "-" -}}
{{- end }}

{{/* The installation's label value on the pod namespaces (render.label_value accepts it as is). */}}
{{- define "appstore.environment" -}}
{{- default .Release.Namespace .Values.environment -}}
{{- end }}

{{- define "appstore.labels" -}}
app.kubernetes.io/name: appstore
app.kubernetes.io/instance: {{ .context.Release.Name }}
app.kubernetes.io/part-of: {{ include "appstore.fullname" .context }}
app.kubernetes.io/managed-by: {{ .context.Release.Service }}
{{- if .component }}
app.kubernetes.io/component: {{ .component }}
{{- end }}
{{- end }}

{{- define "appstore.selectorLabels" -}}
app.kubernetes.io/part-of: {{ include "appstore.fullname" .context }}
app.kubernetes.io/component: {{ .component }}
{{- end }}

{{/* <registry>/<name>:<tag> or <registry>/<name>@<digest>; fails without a tag. */}}
{{- define "appstore.image" -}}
{{- $tag := required (printf "images.tags.%s is required (k8s/env/appstore.yaml)" .key) (index .context.Values.images.tags .key) -}}
{{- if hasPrefix "sha256:" $tag -}}
{{- printf "%s/%s@%s" .context.Values.images.registry .name $tag -}}
{{- else -}}
{{- printf "%s/%s:%s" .context.Values.images.registry .name $tag -}}
{{- end -}}
{{- end }}

{{- define "appstore.podDefaults" -}}
{{- with .Values.images.pullSecrets }}
imagePullSecrets:
{{- range . }}
  - name: {{ . }}
{{- end }}
{{- end }}
enableServiceLinks: false
{{- end }}

{{/* Container hardening of every component except the VM executor. */}}
{{- define "appstore.restricted" -}}
runAsNonRoot: true
allowPrivilegeEscalation: false
readOnlyRootFilesystem: true
capabilities:
  drop: ["ALL"]
seccompProfile:
  type: RuntimeDefault
{{- end }}

{{- define "appstore.secretEnv" -}}
- name: {{ .name }}
  valueFrom:
    secretKeyRef:
      name: {{ .context.Values.secretName }}
      key: {{ .key }}
{{- end }}

{{/* Pod limits, read by API and pod deployer alike (the worker checks the spec again). */}}
{{- define "appstore.podLimitsEnv" -}}
{{- $p := .Values.podApps -}}
- { name: APP_IMAGE_REGISTRY_ALLOWLIST, value: {{ join "," $p.imageRegistryAllowlist | quote }} }
- { name: APP_MAX_CPU, value: {{ $p.maxCpu | quote }} }
- { name: APP_MAX_MEMORY, value: {{ $p.maxMemory | quote }} }
- { name: APP_MAX_STORAGE, value: {{ $p.maxStorage | quote }} }
- { name: K8S_MAX_WORKLOADS_PER_DEPLOYMENT, value: {{ $p.maxWorkloadsPerDeployment | quote }} }
- { name: K8S_ZONE, value: {{ $p.zone | quote }} }
- { name: K8S_APP_DOMAIN, value: {{ $p.appDomain | quote }} }
- { name: K8S_ENVIRONMENT, value: {{ include "appstore.environment" . | quote }} }
{{- end }}

{{/*
What every process of the backend image reads at import: its settings refuse
to start in production without them (.github#7 O).
*/}}
{{- define "appstore.backendEnv" -}}
{{- $k := .Values.keycloak -}}
- { name: APP_ENV, value: production }
{{ include "appstore.secretEnv" (dict "context" . "name" "DATABASE_URL" "key" "database-url") }}
{{ include "appstore.secretEnv" (dict "context" . "name" "CREDENTIAL_ENCRYPTION_KEY" "key" "credential-encryption-key") }}
{{ include "appstore.secretEnv" (dict "context" . "name" "RESULTS_ENCRYPTION_KEY" "key" "results-encryption-key") }}
- { name: KEYCLOAK_SERVER_URL, value: {{ $k.serverUrl | quote }} }
- { name: KEYCLOAK_REALM, value: {{ $k.realm | quote }} }
- { name: KEYCLOAK_ISSUER, value: {{ printf "https://%s/realms/%s" (required "ssoHost is required" .Values.ssoHost) $k.realm | quote }} }
- { name: KEYCLOAK_CLIENT_ID, value: {{ $k.backendClientId | quote }} }
{{ include "appstore.secretEnv" (dict "context" . "name" "KEYCLOAK_CLIENT_SECRET" "key" "keycloak-client-secret") }}
- { name: OIDC_ALLOWED_CLIENTS, value: {{ $k.frontendClientId | quote }} }
- { name: OIDC_AUDIENCE, value: {{ $k.audience | quote }} }
# Same origin: the frontend's nginx is the gateway for /api.
- { name: CORS_ORIGINS, value: "[]" }
- { name: APP_BASE_URL, value: {{ printf "https://%s" (required "host is required" .Values.host) | quote }} }
- { name: APP_GIT_ALLOWED_HOSTS, value: {{ .Values.api.gitAllowedHosts | quote }} }
- { name: OPENSTACK_ALLOWED_AUTH_URLS, value: {{ .Values.api.openstackAllowedAuthUrls | quote }} }
- { name: LTI13_PLATFORM_ISSUER, value: {{ .Values.api.lti.platformIssuer | quote }} }
- { name: LTI13_CLIENT_ID, value: {{ .Values.api.lti.clientId | quote }} }
- { name: LTI13_DEPLOYMENT_ID, value: {{ .Values.api.lti.deploymentId | quote }} }
- { name: LTI13_PLATFORM_JWKS_URL, value: {{ .Values.api.lti.jwksUrl | quote }} }
- { name: LTI13_REDIRECT_URI, value: {{ printf "https://%s/api/lti13/launch" .Values.host | quote }} }
{{ include "appstore.secretEnv" (dict "context" . "name" "LTI13_SESSION_SECRET" "key" "lti13-session-secret") }}
{{ include "appstore.podLimitsEnv" . }}
- { name: K8S_MAX_WORKLOADS_PER_OWNER, value: {{ .Values.podApps.maxWorkloadsPerOwner | quote }} }
- { name: TEMP_REPO_BASE_PATH, value: /tmp/repos }
{{- end }}

{{/*
Both workers seal task results with the results key. Only the VM executor
also gets the credential key (vm-executor.yaml): the pod deployer can read
the job queue, where the VM jobs' credential envelopes travel, and has no
business decrypting them.
*/}}
{{- define "appstore.workerEnv" -}}
- { name: APP_ENV, value: production }
{{ include "appstore.secretEnv" (dict "context" . "name" "DATABASE_URL" "key" "worker-database-url") }}
{{ include "appstore.secretEnv" (dict "context" . "name" "RESULTS_ENCRYPTION_KEY" "key" "results-encryption-key") }}
{{- end }}

{{/* Liveness of a Celery worker: its main process touches the heartbeat file every 30 s. */}}
{{- define "appstore.workerProbe" -}}
livenessProbe:
  exec:
    command:
      - python
      - -c
      - "import os,sys,time; sys.exit(time.time() - os.path.getmtime(os.environ.get('WORKER_HEARTBEAT_FILE', '/tmp/worker-heartbeat')) > 120)"
  initialDelaySeconds: 60
  periodSeconds: 30
  failureThreshold: 3
{{- end }}

{{/* Private and link-local ranges: never "internet". */}}
{{- define "appstore.privateV4" -}}
["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16"]
{{- end }}
{{- define "appstore.privateV6" -}}
["fc00::/7", "fe80::/10"]
{{- end }}

{{/* NetworkPolicy building blocks (networkpolicies.yaml). */}}
{{- define "appstore.netpolPeers" -}}
{{- range .components }}
- podSelector:
    matchLabels:
      app.kubernetes.io/part-of: {{ $.part }}
      app.kubernetes.io/component: {{ . }}
{{- end }}
{{- end }}
{{- define "appstore.internet" -}}
# The internet: everything but the private and link-local ranges (the cloud's
# metadata service among them) and the cluster's own pods, services and nodes.
- to:
    - ipBlock:
        cidr: 0.0.0.0/0
        except: {{ toJson .v4 }}
    - ipBlock:
        cidr: ::/0
        except: {{ toJson .v6 }}
{{- range .allow }}
    - ipBlock: { cidr: {{ . }} }
{{- end }}
{{- end }}
{{- define "appstore.kubeApi" -}}
- to:
{{- range .cidrs }}
    - ipBlock: { cidr: {{ . }} }
{{- end }}
  ports:
{{- range .ports }}
    - { protocol: TCP, port: {{ . }} }
{{- end }}
{{- end }}
