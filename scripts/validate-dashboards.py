#!/usr/bin/env python3
"""Validate that every dashboard JSON is wired into a ConfigMap + GrafanaDashboard CR.

Covers two layouts:
  * platform dashboards  -- dashboards/<group>/*.json, wired in dashboards/kustomization.yaml
                            with the CRs in dashboards/dashboards.yaml
  * product dashboards   -- products/<product>/dashboards/*.json, wired in that directory's
                            own kustomization.yaml with the CRs alongside it

Enforces a 1:1:1 correspondence (JSON <-> configMapGenerator entry <-> GrafanaDashboard CR),
that each CR's folderRef resolves to a GrafanaFolder somewhere in the repo, and that every
product dashboard overlay is registered in the repo-root kustomization.yaml; exits non-zero
listing every problem.
"""
import os
import sys
import glob
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DASH = os.path.join(ROOT, "dashboards")
PRODUCTS = os.path.join(ROOT, "products")


def load_all(path):
    with open(path) as f:
        return [d for d in yaml.safe_load_all(f) if d]


def rel(path):
    return os.path.relpath(path, ROOT).replace(os.sep, "/")


def known_folders():
    """GrafanaFolder names from the platform folders file and every product overlay."""
    names = set()
    sources = [os.path.join(DASH, "folders.yaml")]
    sources += glob.glob(os.path.join(PRODUCTS, "*", "alerting", "*.yaml"))
    for src in sources:
        if not os.path.exists(src):
            continue
        for doc in load_all(src):
            if doc.get("kind") == "GrafanaFolder":
                names.add(doc.get("metadata", {}).get("name"))
    return names


def collect_crs(paths):
    """configMapRef.name -> (cr name, key, folderRef) for every GrafanaDashboard found."""
    out = {}
    for path in paths:
        for doc in load_all(path):
            if doc.get("kind") != "GrafanaDashboard":
                continue
            spec = doc.get("spec", {})
            ref = spec.get("configMapRef") or {}
            out[ref.get("name")] = (
                doc.get("metadata", {}).get("name"), ref.get("key"), spec.get("folderRef"))
    return out


def check_set(label, json_files, kust_path, cr_paths, folders, hint, errors):
    """json_files are paths relative to the kustomization file's directory."""
    kust = load_all(kust_path)[0]
    file_to_cm, cm_to_file = {}, {}
    for g in kust.get("configMapGenerator", []) or []:
        name = g.get("name")
        for fp in g.get("files", []) or []:
            file_to_cm[fp] = name
            cm_to_file[name] = fp

    ref_to_cr = collect_crs(cr_paths)

    # (a) every JSON is wired into a configMapGenerator
    for jf in json_files:
        if jf not in file_to_cm:
            errors.append(f"{label}: {jf} is not wired into a ConfigMap.\n{hint(jf)}")

    # (b) every configMapGenerator file exists on disk
    for fp, name in file_to_cm.items():
        if fp not in json_files:
            errors.append(
                f"{label}: {rel(kust_path)}: configMapGenerator '{name}' "
                f"references missing file '{fp}'.")

    # (c) every ConfigMap has a GrafanaDashboard CR
    for name in sorted(cm_to_file):
        if name not in ref_to_cr:
            errors.append(
                f"{label}: ConfigMap '{name}' has no GrafanaDashboard CR "
                f"(spec.configMapRef.name) in {', '.join(rel(p) for p in cr_paths)}.")

    # (d) every CR points at a real ConfigMap, with the right key + an existing folder
    for ref, (crname, key, folderref) in ref_to_cr.items():
        if ref not in cm_to_file:
            errors.append(
                f"{label}: GrafanaDashboard '{crname}' references ConfigMap '{ref}' that no "
                f"configMapGenerator produces.")
        else:
            want_key = os.path.basename(cm_to_file[ref])
            if key != want_key:
                errors.append(
                    f"{label}: GrafanaDashboard '{crname}': spec.configMapRef.key is '{key}' "
                    f"but ConfigMap '{ref}' contains '{want_key}'.")
        if folderref not in folders:
            errors.append(
                f"{label}: GrafanaDashboard '{crname}': folderRef '{folderref}' has no "
                f"GrafanaFolder in dashboards/folders.yaml or products/*/alerting/.")

    return len(json_files)


def platform_hint(jf):
    cat, fname = jf.split("/", 1)
    base = fname[:-5]
    return (f"    Add to dashboards/kustomization.yaml:\n"
            f"      - name: dashboard-{cat}-{base}\n"
            f"        files:\n"
            f"          - {jf}\n"
            f"    and a GrafanaDashboard CR in dashboards/dashboards.yaml "
            f"(name external-grafana-{cat}-{base}, folderRef external-grafana-{cat}, "
            f"configMapRef name dashboard-{cat}-{base} key {fname}).")


def product_hint(product):
    def _hint(jf):
        base = jf[:-5]
        return (f"    Add to products/{product}/dashboards/kustomization.yaml:\n"
                f"      - name: dashboard-{product}-{base}\n"
                f"        files:\n"
                f"          - {jf}\n"
                f"    and a GrafanaDashboard CR in that directory "
                f"(name external-grafana-{product}-{base}, "
                f"folderRef external-grafana-{product}, "
                f"configMapRef name dashboard-{product}-{base} key {jf}).")
    return _hint


def main():
    errors = []
    folders = known_folders()
    total = 0

    # ---- platform dashboards ------------------------------------------------
    platform_files = sorted(
        os.path.relpath(p, DASH).replace(os.sep, "/")
        for p in glob.glob(os.path.join(DASH, "*", "*.json")))
    total += check_set(
        "platform", platform_files,
        os.path.join(DASH, "kustomization.yaml"),
        [os.path.join(DASH, "dashboards.yaml")],
        folders, platform_hint, errors)

    # ---- product dashboards -------------------------------------------------
    root_kust = load_all(os.path.join(ROOT, "kustomization.yaml"))[0]
    registered = set(root_kust.get("resources", []) or [])

    for pdir in sorted(glob.glob(os.path.join(PRODUCTS, "*", "dashboards"))):
        product = os.path.basename(os.path.dirname(pdir))
        json_files = sorted(os.path.basename(p) for p in glob.glob(os.path.join(pdir, "*.json")))
        if not json_files:
            continue

        kust_path = os.path.join(pdir, "kustomization.yaml")
        if not os.path.exists(kust_path):
            errors.append(
                f"product/{product}: {rel(pdir)} holds dashboard JSON but has no "
                f"kustomization.yaml, so nothing is generated.")
            continue

        overlay = f"products/{product}/dashboards"
        if overlay not in registered:
            errors.append(
                f"product/{product}: overlay '{overlay}' is not listed in the repo-root "
                f"kustomization.yaml, so it is never published in the OCI artifact.")

        cr_paths = [p for p in sorted(glob.glob(os.path.join(pdir, "*.yaml")))
                    if os.path.basename(p) != "kustomization.yaml"]
        total += check_set(
            f"product/{product}", json_files, kust_path, cr_paths,
            folders, product_hint(product), errors)

    if errors:
        print(f"FAIL: dashboard wiring validation ({len(errors)} problem(s)):\n")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)
    print(f"OK: {total} dashboard JSON <-> ConfigMap <-> GrafanaDashboard, "
          f"all folderRefs resolve.")


if __name__ == "__main__":
    main()
