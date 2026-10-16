#!/usr/bin/env python3
"""Fail when a change edits a field that the grafana-operator CRDs make immutable.

Usage: check-immutable-fields.py BASE.yaml HEAD.yaml
(the output of `kustomize build .` on the base branch and on the PR).

The CRDs reject an update that changes an immutable field, such as moving a
GrafanaAlertRuleGroup to another folderRef. kubeconform cannot see this, because it only
validates the new object. In the cluster, Flux's dry-run fails, and since the whole repo
ships as one artifact, nothing is applied until the live object is deleted (2026-10-15,
PR #58).

The rules come from the x-kubernetes-validations transition rules (the ones that mention
oldSelf) in the vendored schemas/, so regenerating the schemas keeps this check current.
A transition rule this script does not recognise is an error (exit 2), not a silent pass;
an immutable field change exits 1.
Objects are matched by apiVersion, kind, namespace and name; new, removed or renamed
objects are not updates and are not checked.
"""
import os
import re
import sys

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMAS = os.path.join(ROOT, "schemas")

# self == oldSelf on the field itself.
RE_EQUAL = re.compile(r"^self\s*==\s*oldSelf$")
# Field X under this node cannot be added or removed.
RE_PRESENCE = re.compile(
    r"^\(\(!has\(oldSelf\.(\w+)\)\s*&&\s*!has\(self\.\1\)\)\s*\|\|"
    r"\s*\(has\(oldSelf\.\1\)\s*&&\s*has\(self\.\1\)\)\)$"
)
# Boolean X under this node cannot go from true to false.
RE_NO_DISABLE = re.compile(
    r"^!oldSelf\.(\w+)\s*\|\|\s*\(oldSelf\.\1\s*&&\s*self\.\1\)$"
)

MISSING = object()


def transition_rules(schema_path):
    """Return [(path, kind, field, message)] for every oldSelf rule in a schema."""
    with open(schema_path) as f:
        schema = yaml.safe_load(f)
    rules, unknown = [], []

    def walk(node, path):
        if not isinstance(node, dict):
            return
        for v in node.get("x-kubernetes-validations", []):
            rule = v["rule"].strip()
            if "oldSelf" not in rule:
                continue
            msg = v.get("message", rule)
            if "[]" in path or "*" in path:
                unknown.append(f"{'.'.join(path)}: {rule} (inside a list or map)")
            elif RE_EQUAL.match(rule):
                rules.append((path, "equal", None, msg))
            elif m := RE_PRESENCE.match(rule):
                rules.append((path, "presence", m.group(1), msg))
            elif m := RE_NO_DISABLE.match(rule):
                rules.append((path, "no-disable", m.group(1), msg))
            else:
                unknown.append(f"{'.'.join(path) or '.'}: {rule}")
        for k, child in node.get("properties", {}).items():
            walk(child, path + [k])
        if "items" in node:
            walk(node["items"], path + ["[]"])
        if isinstance(node.get("additionalProperties"), dict):
            walk(node["additionalProperties"], path + ["*"])

    walk(schema, [])
    return rules, unknown


def get(obj, path):
    for key in path:
        if not isinstance(obj, dict) or key not in obj:
            return MISSING
        obj = obj[key]
    return obj


def load(path):
    with open(path) as f:
        docs = [d for d in yaml.safe_load_all(f) if d]
    out = {}
    for d in docs:
        md = d.get("metadata", {})
        out[(d.get("apiVersion"), d.get("kind"), md.get("namespace"), md.get("name"))] = d
    return out


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    base, head = load(sys.argv[1]), load(sys.argv[2])
    cache, problems, unknown_rules = {}, [], []

    for key in sorted(set(base) & set(head), key=str):
        api_version, kind, ns, name = key
        schema = os.path.join(
            SCHEMAS, f"{kind.lower()}_{api_version.rsplit('/', 1)[-1]}.json"
        )
        if not os.path.exists(schema):
            continue  # not a vendored Grafana kind
        if schema not in cache:
            cache[schema] = transition_rules(schema)
            unknown_rules += [f"{os.path.basename(schema)} {u}" for u in cache[schema][1]]
        old, new = base[key], head[key]
        for path, rule, field, msg in cache[schema][0]:
            o, n = get(old, path), get(new, path)
            # Kubernetes only evaluates a transition rule when the node exists in both.
            if o is MISSING or n is MISSING:
                continue
            if rule == "equal":
                bad = o != n
                before, after = o, n
            else:
                o_f = o.get(field, MISSING) if isinstance(o, dict) else MISSING
                n_f = n.get(field, MISSING) if isinstance(n, dict) else MISSING
                if rule == "presence":
                    bad = (o_f is MISSING) != (n_f is MISSING)
                else:
                    bad = o_f is True and n_f is not True
                before = "<unset>" if o_f is MISSING else o_f
                after = "<unset>" if n_f is MISSING else n_f
            if bad:
                where = ".".join(path + ([field] if field else []))
                problems.append(
                    f"{kind} {ns}/{name}: {where} {before!r} -> {after!r} ({msg})"
                )

    if unknown_rules:
        print("ERROR: transition rules this script does not understand; teach it:")
        for u in unknown_rules:
            print(f"  - {u}")
    if problems:
        print("ERROR: this change edits immutable fields. Flux's dry-run will reject these")
        print("objects and block the WHOLE grafana artifact until each live object is deleted:")
        for p in sorted(set(problems)):
            print(f"  - {p}")
        print()
        print("If the change is intended: after merging, delete each object above on")
        print("admin-prod-aks (`kubectl -n grafana delete <kind> <name>`), then reconcile the")
        print("`grafana-central-grafana-content` Kustomization so Flux recreates it. Keep rule")
        print("and dashboard UIDs unchanged. Add the `immutable-change-ack` label to the PR")
        print("to let this check pass.")
    if unknown_rules:
        sys.exit(2)  # not bypassed by the immutable-change-ack label
    if problems:
        sys.exit(1)
    print(f"OK: {len(set(base) & set(head))} objects compared, no immutable field changed.")


if __name__ == "__main__":
    main()
