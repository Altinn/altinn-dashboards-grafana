#!/usr/bin/env python3
"""Validate that every dashboard JSON is wired into a ConfigMap + GrafanaDashboard CR.

Enforces a 1:1:1 correspondence (JSON <-> configMapGenerator entry <-> GrafanaDashboard CR)
and that each CR's folderRef resolves; exits non-zero listing every problem.
"""
import os
import sys
import glob
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DASH = os.path.join(ROOT, "dashboards")


def load_all(path):
    with open(path) as f:
        return [d for d in yaml.safe_load_all(f) if d]


def main():
    errors = []

    json_files = sorted(
        os.path.relpath(p, DASH).replace(os.sep, "/")
        for p in glob.glob(os.path.join(DASH, "*", "*.json"))
    )

    kust = load_all(os.path.join(DASH, "kustomization.yaml"))[0]
    file_to_cm = {}
    cm_to_file = {}
    for g in kust.get("configMapGenerator", []) or []:
        name = g.get("name")
        for fp in g.get("files", []) or []:
            file_to_cm[fp] = name
            cm_to_file[name] = fp

    crs = [d for d in load_all(os.path.join(DASH, "dashboards.yaml"))
           if d.get("kind") == "GrafanaDashboard"]
    ref_to_cr = {}
    for cr in crs:
        spec = cr.get("spec", {})
        ref = (spec.get("configMapRef") or {})
        ref_to_cr[ref.get("name")] = (
            cr.get("metadata", {}).get("name"), ref.get("key"), spec.get("folderRef"))

    folders = {d.get("metadata", {}).get("name")
               for d in load_all(os.path.join(DASH, "folders.yaml"))
               if d.get("kind") == "GrafanaFolder"}

    # (a) every JSON is wired into a configMapGenerator
    for jf in json_files:
        if jf not in file_to_cm:
            cat, fname = jf.split("/", 1)
            base = fname[:-5]
            errors.append(
                f"dashboards/{jf} is not wired into a ConfigMap.\n"
                f"    Add to dashboards/kustomization.yaml:\n"
                f"      - name: dashboard-{cat}-{base}\n"
                f"        files:\n"
                f"          - {jf}\n"
                f"    and a GrafanaDashboard CR in dashboards/dashboards.yaml "
                f"(name external-grafana-{cat}-{base}, folderRef external-grafana-{cat}, "
                f"configMapRef name dashboard-{cat}-{base} key {fname}).")

    # (b) every configMapGenerator file exists on disk
    for fp, name in file_to_cm.items():
        if fp not in json_files:
            errors.append(
                f"dashboards/kustomization.yaml: configMapGenerator '{name}' "
                f"references missing file '{fp}'.")

    # (c) every ConfigMap has a GrafanaDashboard CR
    for name in sorted(cm_to_file):
        if name not in ref_to_cr:
            errors.append(
                f"ConfigMap '{name}' has no GrafanaDashboard CR "
                f"(spec.configMapRef.name) in dashboards/dashboards.yaml.")

    # (d) every CR points at a real ConfigMap, with the right key + an existing folder
    for ref, (crname, key, folderref) in ref_to_cr.items():
        if ref not in cm_to_file:
            errors.append(
                f"GrafanaDashboard '{crname}' references ConfigMap '{ref}' that no "
                f"configMapGenerator produces.")
        else:
            want_key = os.path.basename(cm_to_file[ref])
            if key != want_key:
                errors.append(
                    f"GrafanaDashboard '{crname}': spec.configMapRef.key is '{key}' "
                    f"but ConfigMap '{ref}' contains '{want_key}'.")
        if folderref not in folders:
            errors.append(
                f"GrafanaDashboard '{crname}': folderRef '{folderref}' has no "
                f"GrafanaFolder in dashboards/folders.yaml.")

    if errors:
        print(f"FAIL: dashboard wiring validation ({len(errors)} problem(s)):\n")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)
    print(f"OK: {len(json_files)} dashboard JSON <-> ConfigMap <-> GrafanaDashboard, "
          f"all folderRefs resolve.")


if __name__ == "__main__":
    main()
