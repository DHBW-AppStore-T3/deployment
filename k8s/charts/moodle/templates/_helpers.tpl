{{- define "moodle.labels" -}}
app.kubernetes.io/name: moodle
app.kubernetes.io/instance: {{ .context.Release.Name }}
app.kubernetes.io/part-of: moodle
app.kubernetes.io/managed-by: {{ .context.Release.Service }}
app.kubernetes.io/component: {{ .component }}
{{- end }}

{{- define "moodle.selectorLabels" -}}
app.kubernetes.io/part-of: moodle
app.kubernetes.io/component: {{ .component }}
{{- end }}

{{/* <registry>/moodle_appstore@sha256:... or :<tag>; fails without one. */}}
{{- define "moodle.image" -}}
{{- $tag := required "images.tags.moodle is required (k8s/images/<env>.yaml)" .Values.images.tags.moodle -}}
{{- if hasPrefix "sha256:" $tag -}}
{{- printf "%s/moodle_appstore@%s" .Values.images.registry $tag -}}
{{- else -}}
{{- printf "%s/moodle_appstore:%s" .Values.images.registry $tag -}}
{{- end -}}
{{- end }}

{{- define "moodle.podDefaults" -}}
{{- with .Values.images.pullSecrets }}
imagePullSecrets:
{{- range . }}
  - name: {{ . }}
{{- end }}
{{- end }}
enableServiceLinks: false
automountServiceAccountToken: false
securityContext:
  runAsNonRoot: true
  runAsUser: 33
  runAsGroup: 33
  fsGroup: 33
  seccompProfile:
    type: RuntimeDefault
{{- end }}

{{- define "moodle.containerSecurity" -}}
allowPrivilegeEscalation: false
readOnlyRootFilesystem: true
capabilities:
  drop: ["ALL"]
{{- end }}

{{/* Everything config.php (docker/config.php of the image) reads. */}}
{{- define "moodle.env" -}}
- { name: MOODLE_WWWROOT, value: {{ printf "https://%s" (required "host is required" .Values.host) | quote }} }
- { name: MOODLE_DB_HOST, value: {{ .Values.db.host | quote }} }
- { name: MOODLE_DB_PORT, value: {{ .Values.db.port | quote }} }
- { name: MOODLE_DB_NAME, value: {{ .Values.db.name | quote }} }
- { name: MOODLE_DB_USER, value: {{ .Values.db.user | quote }} }
- { name: MOODLE_DB_SSLMODE, value: {{ .Values.db.sslmode | quote }} }
- name: MOODLE_DB_PASSWORD
  valueFrom: { secretKeyRef: { name: {{ .Values.secrets.db }}, key: password } }
{{- end }}

{{- define "moodle.volumeMounts" -}}
- { name: moodledata, mountPath: /var/www/moodledata }
- { name: localcache, mountPath: /var/www/localcache }
- { name: tmp, mountPath: /tmp }
{{- end }}

{{- define "moodle.volumes" -}}
- name: moodledata
  persistentVolumeClaim: { claimName: moodle-data }
- name: localcache
  emptyDir: { sizeLimit: {{ .Values.localcacheSizeLimit }} }
- name: tmp
  emptyDir: { sizeLimit: {{ .Values.tmpSizeLimit }} }
{{- end }}
