#!/usr/bin/env python3
"""Regenerate the vendored grafana-operator CRD JSON schemas used by CI (kubeconform).

These are converted from the operator's published CRD bases (openAPIV3Schema) the same way
the Datree CRDs-catalog does it, but pinned to a specific operator version so validation
tracks the cluster's operator. Bump OPERATOR_VERSION when the cluster's grafana-operator
is upgraded, then re-run:  python3 schemas/regenerate.py

Files are named `<kind-lowercased>_v1beta1.json` because kubeconform lowercases the
`{{.ResourceKind}}` template variable when resolving a schema location (same convention as
the Datree CRDs-catalog). Case matters on Linux CI runners — PascalCase names are not found.
"""
import json
import subprocess

OPERATOR_VERSION = "v5.23.0"  # keep in sync with the cluster's grafana-operator

# Kind -> CRD plural (file name in config/crd/bases)
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
    """Mirror openapi2jsonschema: drop `format` (avoids ISO-8601 false positives on Go
    durations like `5m`; the `pattern` still constrains the value), and close objects with
    `additionalProperties: false` so kubeconform -strict catches typo'd fields — except
    x-kubernetes-preserve-unknown-fields nodes (model/settings), which stay open."""
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
        # curl uses the OS trust store — reliable on macOS dev machines and Linux CI alike
        # (avoids the python.org build's missing-CA-bundle SSL errors).
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
