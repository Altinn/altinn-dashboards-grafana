#!/usr/bin/env python3
"""Generate the public (externally shared) copies of platform dashboards.

Public dashboards on the grafana-public instance (dashboards.altinn.cloud) cannot use
template variables: Grafana interpolates them in the browser, and a shared dashboard runs
its queries server-side without them. Built-in variables such as $__range are interpolated
by the datasource backend and keep working.

For every dashboard in SOURCES this script writes a copy under public/dashboards/ with:
  * every template variable removed, and each reference to it ($var, ${var}, ${var:fmt},
    [[var]]) replaced with the variable's "All" value (allValue), so the copy shows what
    the source shows with "All" selected. A variable without includeAll + allValue fails,
    since there is no single value to substitute.
  * datasource references rewritten from the dis-grafana-prod UID to the grafana-public
    datasource (gitops-manifests oci/grafana-public/datasource.yaml), which reads the same
    Azure Monitor workspace.

The source JSON stays the only thing to edit. Run with --check (CI) to fail when a
generated copy is out of date.
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SOURCES = {
    "dashboards/altinn-uptime/sla-altinn-product.json":
        "public/dashboards/altinn-uptime/sla-altinn-product.json",
    "dashboards/altinn-uptime/sla-service-owners.json":
        "public/dashboards/altinn-uptime/sla-service-owners.json",
}

# dis-grafana-prod datasource UID -> grafana-public datasource
DATASOURCES = {
    "admin-prod-obs-amw": {
        "type": "grafana-azureprometheus-datasource",
        "uid": "azure-managed-prometheus",
    },
}

# Built-in datasources that exist on every instance
BUILTIN_DATASOURCES = {"-- Grafana --", "-- Dashboard --", "-- Mixed --", "__expr__"}


def variable_pattern(name):
    n = re.escape(name)
    return re.compile(rf"\$\{{{n}(?::[A-Za-z]+)?\}}|\[\[{n}(?::[A-Za-z]+)?\]\]|\${n}\b")


def map_strings(node, fn):
    if isinstance(node, dict):
        return {k: map_strings(v, fn) for k, v in node.items()}
    if isinstance(node, list):
        return [map_strings(v, fn) for v in node]
    if isinstance(node, str):
        return fn(node)
    return node


def rewrite_datasources(node, src, errors):
    if isinstance(node, list):
        return [rewrite_datasources(v, src, errors) for v in node]
    if not isinstance(node, dict):
        return node
    out = {}
    for k, v in node.items():
        if k == "datasource" and isinstance(v, dict) and "uid" in v:
            uid = v["uid"]
            if uid in DATASOURCES:
                v = dict(DATASOURCES[uid])
            elif uid not in BUILTIN_DATASOURCES:
                errors.append(f"{src}: datasource uid '{uid}' has no grafana-public mapping "
                              f"(DATASOURCES in {os.path.relpath(__file__, ROOT)})")
        out[k] = rewrite_datasources(v, src, errors)
    return out


def build(src):
    with open(os.path.join(ROOT, src)) as f:
        dash = json.load(f)
    errors = []

    variables = dash.get("templating", {}).get("list", [])
    dash["templating"] = {"list": []}
    for var in variables:
        name = var.get("name")
        all_value = var.get("allValue")
        if not var.get("includeAll") or all_value is None:
            errors.append(f"{src}: variable '{name}' has no includeAll + allValue to substitute")
            continue
        pattern = variable_pattern(name)
        dash = map_strings(dash, lambda s, p=pattern, a=all_value: p.sub(lambda _: a, s))
        leftover = []
        map_strings(dash, lambda s, p=pattern: leftover.append(s) if p.search(s) else s)
        if leftover:
            errors.append(f"{src}: variable '{name}' still referenced after substitution")

    dash = rewrite_datasources(dash, src, errors)
    return json.dumps(dash, indent=2, ensure_ascii=False) + "\n", errors


def main():
    check = "--check" in sys.argv[1:]
    errors, stale = [], []
    for src, dst in SOURCES.items():
        content, errs = build(src)
        errors += errs
        if errs:
            continue
        path = os.path.join(ROOT, dst)
        current = open(path).read() if os.path.exists(path) else None
        if current == content:
            continue
        if check:
            stale.append(dst)
        else:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                f.write(content)
            print(f"wrote {dst}")

    if errors:
        print("FAIL: cannot generate public dashboards:\n")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)
    if stale:
        print("FAIL: public dashboards are out of date with their source. Run "
              "python3 scripts/build-public-dashboards.py and commit the result:\n")
        for s in stale:
            print(f"  - {s}")
        sys.exit(1)
    print(f"OK: {len(SOURCES)} public dashboard(s) up to date.")


if __name__ == "__main__":
    main()
