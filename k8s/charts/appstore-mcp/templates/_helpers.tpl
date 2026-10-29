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
["0.0.0.0/8", "10.0.0.0/8", "100.64.0.0/10", "127.0.0.0/8", "169.254.0.0/16", "172.16.0.0/12", "192.0.0.0/24", "192.168.0.0/16", "198.18.0.0/15", "224.0.0.0/3"]
{{- end }}
{{- define "mcp.privateV6" -}}
["::1/128", "64:ff9b::/96", "64:ff9b:1::/48", "100::/64", "2002::/16", "fc00::/7", "fe80::/10", "fec0::/10", "ff00::/8"]
{{- end }}
