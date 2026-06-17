#!/usr/bin/env python3
"""Regenerate the vendored grafana-operator CRD JSON schemas used by CI (kubeconform).

Pinned to OPERATOR_VERSION; Renovate bumps it and the regenerate-schemas workflow
refreshes the vendored JSON to match.
"""
import json
import subprocess

# renovate: datasource=github-releases depName=grafana/grafana-operator
OPERATOR_VERSION = "v5.23.0"

KINDS = {
    "GrafanaAlertRuleGroup": "grafanaalertrulegroups",
    "GrafanaContactPoint": "grafanacontactpoints",
    "GrafanaDashboard": "grafanadashboards",
    "GrafanaFolder": "grafanafolders",
    "GrafanaNotificationPolicy": "grafananotificationpolicies",
    "GrafanaNotificationPolicyRoute": "grafananotificationpolicyroutes",
}
BASE = ("https://raw.githubusercontent.com/grafana/grafana-operator/"
        f"{OPERATOR_VERSION}/config/crd/bases/grafana.integreatly.org_")


def transform(node):
    """Drop `format` (avoids false positives on Go durations like `5m`) and close objects
    with `additionalProperties: false`, except x-kubernetes-preserve-unknown-fields nodes."""
    if isinstance(node, dict):
        node.pop("format", None)
        for v in node.values():
            transform(v)
        if "additionalProperties" not in node:
            if node.get("x-kubernetes-preserve-unknown-fields") is True:
                node["additionalProperties"] = True
            elif "properties" in node:
                node["additionalProperties"] = False
    elif isinstance(node, list):
        for v in node:
            transform(v)
    return node


def main():
    import yaml  # PyYAML, to parse the CRD bases
    for kind, plural in KINDS.items():
        # curl uses the OS trust store (avoids the python.org build's missing-CA SSL errors).
        raw = subprocess.run(
            ["curl", "-fsSL", BASE + plural + ".yaml"],
            check=True, capture_output=True, text=True,
        ).stdout
        crd = yaml.safe_load(raw)
        version = next(v for v in crd["spec"]["versions"] if v["name"] == "v1beta1")
        schema = transform(version["schema"]["openAPIV3Schema"])
        out = f"schemas/{kind.lower()}_v1beta1.json"   # kubeconform lowercases {{.ResourceKind}}
        with open(out, "w") as f:
            json.dump(schema, f, indent=2, sort_keys=True)
            f.write("\n")
        print(f"wrote {out}")
    print(f"\nPinned to grafana-operator {OPERATOR_VERSION}")


if __name__ == "__main__":
    main()
