{{- define "mcp.name" -}}appstore-mcp{{- end }}

{{- define "mcp.clusterName" -}}
{{- printf "appstore-mcp-%s" .Release.Namespace | trunc 63 | trimSuffix "-" -}}
{{- end }}

{{- define "mcp.labels" -}}
app.kubernetes.io/name: appstore-mcp
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/part-of: appstore-mcp
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "mcp.selector" -}}
app.kubernetes.io/name: appstore-mcp
app.kubernetes.io/part-of: appstore-mcp
{{- end }}

{{- define "mcp.image" -}}
{{- $tag := required "images.tags.appstoreMcp is required (k8s/images/<env>.yaml)" .Values.images.tags.appstoreMcp -}}
{{- if hasPrefix "sha256:" $tag -}}
{{- printf "%s/appstore-mcp@%s" .Values.images.registry $tag -}}
{{- else -}}
{{- printf "%s/appstore-mcp:%s" .Values.images.registry $tag -}}
{{- end -}}
{{- end }}

{{/* Private and link-local ranges: never "internet". */}}
{{- define "mcp.privateV4" -}}
["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16"]
{{- end }}
{{- define "mcp.privateV6" -}}
["fc00::/7", "fe80::/10"]
{{- end }}
