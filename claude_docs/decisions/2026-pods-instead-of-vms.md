# Entscheidung: Apps als Pods statt als VMs (.github#4)

## Kontext
Apps liefen als OpenTofu/Packer-Code, den der Worker ausführt. Das ist eine Lizenzfrage (BSL) und vor allem ein
Sicherheitsproblem (fremder Code im Worker), dazu langsam (Packer-Builds) und betriebsintensiv. Der Cluster ist da.

## Entscheidung
1. **Option A:** Die Plattform rendert alle Kubernetes-Objekte selbst aus einer kleinen Spec (`appstore.yaml`,
   App-Vertrag v2). Keine Helm-Charts/Manifeste von App-Autor:innen, kein Image-Build im AppStore.
2. **Freigabe = Commit + Spec-Hash + Image-Digests.** Images nur per Digest aus einer Registry-Allowlist.
3. **Worker-Rechte:** Eigener ServiceAccount darf Namespaces `dep-*` anlegen/löschen und dort genau eine ClusterRole
   binden (`bind`); eine ValidatingAdmissionPolicy erzwingt das (Namespace-Präfix, Pflichtlabel, nur diese
   RoleBinding, keine privilegierten Pods/hostPath/Host-Namespaces in StatefulSets). Der Worker hat kein
   clusterweites Secret-Recht.
4. **Zustand:** Es gibt keinen Terraform-State. Zustand = Namespace im Cluster (Label `appstore.dhbw/deployment-id`).
   Zugangsdaten bleiben in den verschlüsselten Task-Outputs (`user_accounts`/`team_vms`), unverändert für `my-access`
   (Schlüssel `<team>-<account>`); `deployment_access` als eigene Tabelle ist nicht nötig.
5. **Koexistenz:** `runtime` je Version/Deployment; VM-Apps (Windows, Bestand) laufen unverändert. Pod-Deployments haben
   `os_project_id = "kubernetes"` und brauchen kein Credential.
6. **Passwort (MVP)** über TLS statt SSO vor den Ingresses.
7. **Hostnamen** `<workload>-<deployment>.<appDomain>`: Der Cluster hat nur ein Wildcard-Zertifikat `*.<zone>` und
   einen Default-TLSStore. Die Hosts liegen deshalb direkt unter der Zone (ein Label), nicht unter `apps.<zone>`.

## Offen (bewusst nicht im MVP)
- Cluster-Topologie: eigene Worker-Nodes mit Taint (`podApps.studentNodeSelector/Tolerations` sind vorbereitet,
  der Cluster hat nur einen Node) bzw. eigener Workload-Cluster (Magnum). Gespräch mit Prof. Pfisterer.
- Speicher: k3s `local-path` ist knotengebunden, ohne Backup. Longhorn/Cinder-CSI vor Produktion.
- Egress „Internet" gilt je App (`egress`); IPv6-Internet aus Pods braucht NAT66/Routing und ist ungeprüft.
- Datei-Variablen > 1 MiB (Init-Container in die PVC).
- Windows-Desktop bleibt VM; KubeVirt, Operator mit CRD und Plattform-OIDC sind eigene Themen.
