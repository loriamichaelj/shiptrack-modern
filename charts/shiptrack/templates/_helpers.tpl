{{/* The image reference, always by digest. */}}
{{- define "shiptrack.image" -}}
{{ required "image.repository is required" .Values.image.repository }}@{{ required "image.digest is required" .Values.image.digest }}
{{- end -}}

{{- define "shiptrack.labels" -}}
app.kubernetes.io/name: shiptrack
app.kubernetes.io/instance: {{ .root.Release.Name }}
app.kubernetes.io/component: {{ .component }}
app.kubernetes.io/managed-by: {{ .root.Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .root.Chart.Name .root.Chart.Version | replace "+" "_" }}
{{- end -}}

{{- define "shiptrack.selectorLabels" -}}
app.kubernetes.io/name: shiptrack
app.kubernetes.io/instance: {{ .root.Release.Name }}
app.kubernetes.io/component: {{ .component }}
{{- end -}}

{{/* Pod-level security: non-root, the runtime's default seccomp profile (Pod Security "restricted"). */}}
{{- define "shiptrack.podSecurityContext" -}}
runAsNonRoot: true
runAsUser: 10001
runAsGroup: 10001
fsGroup: 10001
seccompProfile:
  type: RuntimeDefault
{{- end -}}

{{- define "shiptrack.containerSecurityContext" -}}
allowPrivilegeEscalation: false
readOnlyRootFilesystem: true
capabilities:
  drop: ["ALL"]
{{- end -}}

{{/* The root filesystem is read-only; Starlette spools large uploads to /tmp. */}}
{{- define "shiptrack.tmpVolume" -}}
- name: tmp
  emptyDir:
    sizeLimit: 64Mi
{{- end -}}

{{- define "shiptrack.tmpMount" -}}
- name: tmp
  mountPath: /tmp
{{- end -}}

{{/* One zone and one host spread, soft, so a small cluster still schedules. */}}
{{- define "shiptrack.topologySpread" -}}
- maxSkew: 1
  topologyKey: topology.kubernetes.io/zone
  whenUnsatisfiable: ScheduleAnyway
  labelSelector:
    matchLabels:
      {{- include "shiptrack.selectorLabels" . | nindent 6 }}
- maxSkew: 1
  topologyKey: kubernetes.io/hostname
  whenUnsatisfiable: ScheduleAnyway
  labelSelector:
    matchLabels:
      {{- include "shiptrack.selectorLabels" . | nindent 6 }}
{{- end -}}

{{/* Settings every role shares. Roles add their own on top. */}}
{{- define "shiptrack.commonEnv" -}}
- name: AWS_REGION
  value: {{ .Values.region | quote }}
- name: SHIPTRACK_LOG_LEVEL
  value: {{ .Values.logLevel | quote }}
- name: SHIPTRACK_SCHEMA_COMPAT
  value: {{ .Values.schemaCompat | quote }}
{{- end -}}

{{/* The database settings for a role, with that role's pool. */}}
{{- define "shiptrack.dbEnv" -}}
- name: SHIPTRACK_DB_SECRET_ARN
  value: {{ required "aws.dbSecretArn is required" .root.Values.aws.dbSecretArn | quote }}
- name: SHIPTRACK_DB_POOL_SIZE
  value: {{ .pool.size | quote }}
- name: SHIPTRACK_DB_MAX_OVERFLOW
  value: {{ .pool.maxOverflow | quote }}
{{- end -}}
