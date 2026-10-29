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
{{- $tag := required (printf "images.tags.%s is required (k8s/images/<env>.yaml)" .key) (index .context.Values.images.tags .key) -}}
{{- if hasPrefix "sha256:" $tag -}}
{{- printf "%s/%s@%s" .context.Values.images.registry .name $tag -}}
{{- else -}}
{{- printf "%s/%s:%s" .context.Values.images.registry .name $tag -}}
{{- end -}}
{{- end }}

{{/* The noVNC proxy image the pod deployer puts into kubevirt-vm deployments:
pinned by digest (images.tags.novncProxy, written by k8s-bump). Until the
first bump it is the unpinned :latest, as before. */}}
{{- define "appstore.vncProxyImage" -}}
{{- $tag := .Values.images.tags.novncProxy | default "" -}}
{{- if not $tag -}}
{{- printf "%s/novnc-proxy:latest" .Values.images.registry -}}
{{- else -}}
{{- include "appstore.image" (dict "context" . "key" "novncProxy" "name" "novnc-proxy") -}}
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
- { name: APP_VM_IMAGE_NAMESPACES, value: {{ join "," $p.vmImageNamespaces | quote }} }
- { name: K8S_MAX_WORKLOADS_PER_DEPLOYMENT, value: {{ $p.maxWorkloadsPerDeployment | quote }} }
- { name: K8S_ZONE, value: {{ $p.zone | quote }} }
- { name: K8S_APP_DOMAIN, value: {{ $p.appDomain | quote }} }
- { name: K8S_ENVIRONMENT, value: {{ include "appstore.environment" . | quote }} }
# How long a deploy waits for its pods; the API's live view uses it too.
- { name: K8S_READY_TIMEOUT_SECONDS, value: {{ $p.readyTimeoutSeconds | quote }} }
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
- { name: OIDC_ALLOWED_CLIENTS, value: {{ join "," (compact (list $k.frontendClientId (ternary $k.selfServiceClientId "" .Values.selfServiceUi.enabled))) | quote }} }
- { name: OIDC_AUDIENCE, value: {{ $k.audience | quote }} }
# Same origin: the frontend's nginx is the gateway for /api.
- { name: CORS_ORIGINS, value: "[]" }
# The other UI whose pages may change state through the API (the API refuses
# writes a browser sends for any other page: student apps share the site).
{{- if and .Values.selfServiceUi.enabled .Values.selfServiceHost }}
- { name: CSRF_TRUSTED_ORIGINS, value: {{ printf "https://%s" .Values.selfServiceHost | quote }} }
{{- end }}
- { name: APP_BASE_URL, value: {{ printf "https://%s" (required "host is required" .Values.host) | quote }} }
- { name: APP_GIT_ALLOWED_HOSTS, value: {{ .Values.api.gitAllowedHosts | quote }} }
- { name: LTI13_PLATFORM_ISSUER, value: {{ .Values.api.lti.platformIssuer | quote }} }
- { name: LTI13_CLIENT_ID, value: {{ .Values.api.lti.clientId | quote }} }
- { name: LTI13_DEPLOYMENT_ID, value: {{ .Values.api.lti.deploymentId | quote }} }
- { name: LTI13_PLATFORM_JWKS_URL, value: {{ .Values.api.lti.jwksUrl | quote }} }
- { name: LTI13_REDIRECT_URI, value: {{ printf "https://%s/api/lti13/launch" .Values.host | quote }} }
{{ include "appstore.secretEnv" (dict "context" . "name" "LTI13_SESSION_SECRET" "key" "lti13-session-secret") }}
{{ include "appstore.podLimitsEnv" . }}
- { name: K8S_MAX_WORKLOADS_PER_OWNER, value: {{ .Values.podApps.maxWorkloadsPerOwner | quote }} }
- { name: TEMP_REPO_BASE_PATH, value: /tmp/repos }
{{- if .Values.clamav.enabled }}
# ClamAV: when CLAMD_HOST is set the API scans every upload and fails closed.
- { name: CLAMD_HOST, value: {{ include "appstore.name" (dict "context" . "component" "clamav") | quote }} }
- { name: CLAMD_PORT, value: "3310" }
{{- end }}
{{- end }}

{{/*
The pod deployer seals task results with the results key. It gets no
credential key.
*/}}
{{- define "appstore.workerEnv" -}}
- { name: APP_ENV, value: production }
{{ include "appstore.secretEnv" (dict "context" . "name" "DATABASE_URL" "key" "worker-database-url") }}
{{ include "appstore.secretEnv" (dict "context" . "name" "RESULTS_ENCRYPTION_KEY" "key" "results-encryption-key") }}
{{- end }}

{{/* Liveness of the pod deployer: its main loop touches the heartbeat file every few seconds. */}}
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

{{/* Never "internet": private, shared (carrier-grade NAT), link-local (the cloud's metadata
     service) and loopback space, and everything from 224.0.0.0 up (multicast, reserved, the
     limited broadcast); for IPv6 ULA, link-local, site-local, multicast and the prefixes that
     carry IPv4 inside IPv6 (NAT64, 6to4: they would bypass the IPv4 entries). The
     renderer of the pod apps (backend/worker app/k8s/render.py) keeps the same lists, and the
     admission policy admits a student policy only if its list contains every entry here.
     The same lists are in charts/appstore-mcp and charts/moodle. */}}
{{- define "appstore.privateV4" -}}
["0.0.0.0/8", "10.0.0.0/8", "100.64.0.0/10", "127.0.0.0/8", "169.254.0.0/16", "172.16.0.0/12", "192.0.0.0/24", "192.168.0.0/16", "198.18.0.0/15", "224.0.0.0/3"]
{{- end }}
{{- define "appstore.privateV6" -}}
["::1/128", "64:ff9b::/96", "64:ff9b:1::/48", "100::/64", "2002::/16", "fc00::/7", "fe80::/10", "fec0::/10", "ff00::/8"]
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
# The internet over the given TCP ports (443: the platform talks HTTPS only): everything
# but the private, link-local and multicast ranges (the cloud's metadata service among
# them) and the cluster's own pods, services and nodes.
- to:
    - ipBlock:
        cidr: 0.0.0.0/0
        except: {{ toJson .v4 }}
    - ipBlock:
        cidr: ::/0
        except: {{ toJson .v6 }}
  ports:
  {{- range .ports }}
    - { protocol: TCP, port: {{ . }} }
  {{- end }}
{{- if .allow }}
# Addresses in a private range the pod may reach anyway (any port).
- to:
  {{- range .allow }}
    - ipBlock: { cidr: {{ . }} }
  {{- end }}
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
