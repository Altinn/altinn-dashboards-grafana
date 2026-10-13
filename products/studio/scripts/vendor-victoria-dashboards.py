#!/usr/bin/env python3
"""Vendor VictoriaMetrics' official dashboards for Studio's Victoria stack.

Downloads each dashboard in SOURCES from the release tag of the binary it describes and
adapts it to the shared Grafana, writing products/studio/dashboards/<file>:

  * every Prometheus datasource reference is pinned to altinn-studio-metrics, and the
    datasource template variable and the export's __inputs/__requires are removed;
  * the dashboard gets a stable uid and an "Altinn Studio — ..." title, links in its own
    panels follow the new uid, editable is off, and the template variables reload on a
    time range change;
  * the tag altinn-studio-observability and a dashboard link on it connect the dashboards
    to each other and to the overview, and the description and a link record the source.

Nothing else changes, so a dashboard reads as upstream does. Run it again when the image
tags in Altinn/altinn-studio infra/observability/studio/victoria change: bump the tags
below to match, run it, and review the diff. Do not edit the generated JSON by hand.

    python3 products/studio/scripts/vendor-victoria-dashboards.py
"""
import json
import os
import re
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "dashboards")
SCRIPT = "products/studio/scripts/vendor-victoria-dashboards.py"

DATASOURCE = {"type": "prometheus", "uid": "altinn-studio-metrics"}
TAG = "altinn-studio-observability"

# (file, repository, tag, upstream path, uid, title). The tags match the images in
# infra/observability/studio/victoria: VictoriaMetrics v1.153.0 (vmsingle, vmagent), VictoriaLogs
# v1.52.0 (vlsingle, vlagent) and VictoriaTraces v0.12.0 (vtsingle). The operator (v0.75.0)
# has no dashboard of its own repository; VictoriaMetrics ships it.
SOURCES = [
    ("observability-vmsingle.json", "VictoriaMetrics/VictoriaMetrics", "v1.153.0",
     "dashboards/victoriametrics.json", "altinn-studio-victoria-vmsingle",
     "Altinn Studio — VictoriaMetrics single-node"),
    ("observability-vmagent.json", "VictoriaMetrics/VictoriaMetrics", "v1.153.0",
     "dashboards/vmagent.json", "altinn-studio-victoria-vmagent",
     "Altinn Studio — vmagent"),
    ("observability-operator.json", "VictoriaMetrics/VictoriaMetrics", "v1.153.0",
     "dashboards/operator.json", "altinn-studio-victoria-operator",
     "Altinn Studio — VictoriaMetrics operator"),
    ("observability-vlsingle.json", "VictoriaMetrics/VictoriaLogs", "v1.52.0",
     "dashboards/victorialogs.json", "altinn-studio-victoria-vlsingle",
     "Altinn Studio — VictoriaLogs single-node"),
    ("observability-vlagent.json", "VictoriaMetrics/VictoriaLogs", "v1.52.0",
     "dashboards/vlagent.json", "altinn-studio-victoria-vlagent",
     "Altinn Studio — vlagent"),
    ("observability-vtsingle.json", "VictoriaMetrics/VictoriaTraces", "v0.12.0",
     "dashboards/victoriatraces.json", "altinn-studio-victoria-vtsingle",
     "Altinn Studio — VictoriaTraces single-node"),
]


def fetch(repo, tag, path):
    # curl uses the OS trust store, as schemas/regenerate.py does.
    url = f"https://raw.githubusercontent.com/{repo}/{tag}/{path}"
    return json.loads(subprocess.run(
        ["curl", "-fsSL", url], check=True, capture_output=True, text=True).stdout)


def panel_ids(panels):
    for p in panels:
        yield p.get("id")
        yield from panel_ids(p.get("panels", []))


def adapt(dash, repo, tag, path, uid, title):
    for key in ("__inputs", "__elements", "__requires"):
        dash.pop(key, None)

    templating = dash["templating"]["list"]
    ds_vars = {v["name"] for v in templating if v.get("type") == "datasource"}
    templating[:] = [v for v in templating if v.get("type") != "datasource"]
    # Upstream saves selections from its own test instances (a job named vmsingle-homelab),
    # which do not exist here; Grafana then picks the first value. Values are reloaded on a
    # time range change rather than only on load, so the lists follow the range shown.
    for v in templating:
        if v.get("type") == "query":
            v["current"] = {}
            v["refresh"] = 2
    var_refs = {f"${n}" for n in ds_vars} | {f"${{{n}}}" for n in ds_vars}

    def is_var_ref(ds):
        uid_ = ds.get("uid") if isinstance(ds, dict) else ds
        return uid_ in var_refs

    # Panel links open a panel of the dashboard they are in with ?viewPanel=<id>. vlagent's
    # copies of vmagent's panels still carry vmagent's uid, so the target is the panel id.
    own_ids = set(panel_ids(dash["panels"]))
    # A link's var-<name> parameter for a variable this dashboard no longer has (the
    # datasource, which vlagent's links call ds although its variable is DS_PROMETHEUS).
    kept = {v["name"] for v in templating}
    stale_param = re.compile(r"&var-(\w+)=[^&]*")
    view_link = re.compile(r"^/d/[^/?]+\?viewPanel=(\d+)")

    def walk(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if k == "datasource" and is_var_ref(v):
                    node[k] = dict(DATASOURCE)
                elif k == "url" and isinstance(v, str):
                    v = stale_param.sub(lambda m: m[0] if m[1] in kept else "", v)
                    m = view_link.match(v)
                    if m and int(m.group(1)) in own_ids:
                        v = f"/d/{uid}" + v[v.index("?"):]
                    node[k] = v
                else:
                    walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(dash)
    text = json.dumps(dash)
    leftover = [r for r in var_refs | {"$ds", "${ds}", "var-ds="} if r in text]
    if leftover:
        raise SystemExit(f"{path}: datasource variable still referenced: {leftover}")

    source = f"https://github.com/{repo}/blob/{tag}/{path}"
    dash["id"] = None
    dash["uid"] = uid
    dash["title"] = title
    dash["editable"] = False
    dash["tags"] = list(dict.fromkeys(dash.get("tags", []) + [TAG]))
    dash["description"] = (
        f"{dash.get('description', '').rstrip('.')}. Vendored from {repo} {tag} ({path}) by "
        f"{SCRIPT}; re-run it rather than editing this JSON.")
    dash["links"] = [
        {"type": "dashboards", "tags": [TAG], "asDropdown": True, "title": "Observability",
         "includeVars": False, "keepTime": True, "targetBlank": False, "icon": "external link",
         "tooltip": "", "url": ""},
        {"type": "link", "title": f"Upstream {repo.split('/')[1]} {tag}", "url": source,
         "targetBlank": True, "icon": "info", "tags": [], "asDropdown": False,
         "includeVars": False, "keepTime": False, "tooltip": "Source of this dashboard"},
    ] + dash.get("links", [])
    return dash


def main():
    for fname, repo, tag, path, uid, title in SOURCES:
        dash = adapt(fetch(repo, tag, path), repo, tag, path, uid, title)
        with open(os.path.join(OUT, fname), "w") as f:
            json.dump(dash, f, indent=2, ensure_ascii=False)
            f.write("\n")
        print(f"wrote products/studio/dashboards/{fname} from {repo} {tag} {path}")


if __name__ == "__main__":
    main()
