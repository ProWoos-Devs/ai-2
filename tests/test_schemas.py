"""Per-file structural schemas for the declarative YAML (tier definitions,
the model catalog, workflow profiles). test_consistency.py checks that the
files agree with each other; this file checks that each file has the right
shape on its own, so a typo'd key, a wrong type or an out-of-vocabulary value
fails CI instead of surfacing as odd runtime behavior. Hand-rolled checks on
purpose: the engine's only dependency is PyYAML and the tests keep that
discipline (no jsonschema)."""
import datetime
import importlib.resources
import pathlib
import re

import yaml

from ai2.benchmark import STAR_LABELS
from ai2.models import load_catalog
from ai2.tiers import load_tiers, resolve_config

GRANTS = {"full", "basic", "none", "pending-backend"}
RUNTIME_SERVICES = {"on-demand", "persistent"}
MEMORY_MECHANISMS = {"zram", "zswap"}

TIER_KEYS = {"tier", "label", "requires", "config_from", "session", "memory",
             "kernel", "oom_guard", "services", "runtime", "models", "rag",
             "capabilities"}
CATALOG_REQUIRED = {"id", "label", "params_b", "quant", "file_mb",
                    "ram_peak_mb", "repo", "file", "sha256", "verified",
                    "license"}
CATALOG_OPTIONAL = {"benchmark", "sampling", "spec_type_measured"}
SAMPLING_KEYS = {"temp", "top_k", "top_p", "min_p", "repeat_penalty"}
PROFILE_KEYS = {"id", "description", "requests", "tiers"}
PROFILE_TIER_KEYS = {"packages", "models", "llama_server"}


def _tier_files():
    d = importlib.resources.files("ai2").joinpath("data/tiers")
    return sorted((e.name, yaml.safe_load(e.read_text()))
                  for e in d.iterdir() if e.name.endswith(".yml"))


def _profile_files():
    d = pathlib.Path("profiles")
    return sorted((p.name, yaml.safe_load(p.read_text()))
                  for p in d.glob("*.yml"))


def test_tier_files_have_valid_shape():
    tiers = _tier_files()
    ids = {data["tier"] for _, data in tiers}
    for name, data in tiers:
        where = f"tiers/{name}"
        assert set(data) <= TIER_KEYS, f"{where}: unknown keys {set(data) - TIER_KEYS}"
        assert data["tier"] == name.removesuffix(".yml"), f"{where}: tier id != filename"
        assert isinstance(data["label"], str) and data["label"], where
        req = data["requires"]
        assert set(req) == {"ram_gib", "cores"}, f"{where}: requires keys {set(req)}"
        assert isinstance(req["ram_gib"], int) and req["ram_gib"] > 0, where
        assert isinstance(req["cores"], int) and req["cores"] > 0, where
        if "config_from" in data:
            assert data["config_from"] in ids, f"{where}: config_from unknown tier"
            extra = set(data) - {"tier", "label", "requires", "config_from"}
            assert not extra, f"{where}: config_from tiers carry no own config, got {extra}"
        else:
            _check_full_tier_config(where, data)


def _check_full_tier_config(where, data):
    session = data["session"]
    assert isinstance(session.get("desktop"), str) and isinstance(session.get("login"), str), where
    memory = data["memory"]
    assert memory["mechanism"] in MEMORY_MECHANISMS, f"{where}: memory.mechanism"
    for k, v in data["kernel"].items():
        assert isinstance(k, str) and isinstance(v, (int, float)), f"{where}: kernel.{k}"
    assert isinstance(data["oom_guard"], str), where
    never = data["services"]["never"]
    assert isinstance(never, list) and all(isinstance(s, str) for s in never), where
    runtime = data["runtime"]
    assert isinstance(runtime["provider"], str), where
    assert runtime["service"] in RUNTIME_SERVICES, f"{where}: runtime.service"
    if runtime["service"] == "on-demand":
        assert isinstance(runtime.get("idle_timeout_s"), int) and runtime["idle_timeout_s"] > 0, \
            f"{where}: on-demand runtime needs idle_timeout_s"
    models = data["models"]
    assert isinstance(models, list) and models, f"{where}: models must be a non-empty list"
    for m in models:
        assert set(m) == {"id", "quant", "ctx"}, f"{where}: model entry keys {set(m)}"
        assert isinstance(m["id"], str) and isinstance(m["quant"], str), where
        assert isinstance(m["ctx"], int) and m["ctx"] > 0, where
    caps = data["capabilities"]
    assert isinstance(caps, dict) and caps, where
    for cap, grant in caps.items():
        assert grant in GRANTS, f"{where}: capabilities.{cap} = {grant!r}"


def test_catalog_entries_have_valid_shape():
    for m in load_catalog():
        where = f"models.yml: {m.get('id', '<no id>')}"
        keys = set(m)
        assert CATALOG_REQUIRED <= keys, f"{where}: missing {CATALOG_REQUIRED - keys}"
        assert keys <= CATALOG_REQUIRED | CATALOG_OPTIONAL, \
            f"{where}: unknown keys {keys - CATALOG_REQUIRED - CATALOG_OPTIONAL}"
        assert isinstance(m["id"], str) and isinstance(m["label"], str), where
        assert isinstance(m["params_b"], (int, float)) and m["params_b"] > 0, where
        assert isinstance(m["quant"], str) and m["quant"], where
        for k in ("file_mb", "ram_peak_mb"):
            assert isinstance(m[k], int) and m[k] > 0, f"{where}: {k}"
        assert isinstance(m["repo"], str) and "/" in m["repo"], where
        assert isinstance(m["file"], str), where
        assert re.fullmatch(r"[0-9a-f]{64}", m["sha256"]), f"{where}: sha256"
        assert isinstance(m["verified"], datetime.date), f"{where}: verified must be a date"
        assert isinstance(m["license"], str) and m["license"], where
        if "benchmark" in m:
            assert m["benchmark"] is True, where
        if "sampling" in m:
            s = m["sampling"]
            assert set(s) <= SAMPLING_KEYS, f"{where}: sampling keys {set(s) - SAMPLING_KEYS}"
            assert all(isinstance(v, (int, float)) for v in s.values()), where


def test_profile_files_have_valid_shape():
    tiers = load_tiers()
    catalog = {m["id"]: m for m in load_catalog()}
    profiles = _profile_files()
    assert profiles, "profiles/ has no .yml files"
    for name, data in profiles:
        where = f"profiles/{name}"
        assert set(data) == PROFILE_KEYS, f"{where}: keys {set(data) ^ PROFILE_KEYS}"
        assert data["id"] == name.removesuffix(".yml"), f"{where}: id != filename"
        assert isinstance(data["description"], str) and data["description"], where
        requests = data["requests"]
        assert isinstance(requests, list) and requests, where
        unknown = set(requests) - set(STAR_LABELS)
        assert not unknown, f"{where}: requests unknown capabilities {unknown}"
        assert isinstance(data["tiers"], dict) and data["tiers"], where
        for tier_id, block in data["tiers"].items():
            assert tier_id in tiers, f"{where}: unknown tier {tier_id!r}"
            _check_profile_tier_block(where, tier_id, block, requests, tiers, catalog)


def _check_profile_tier_block(where, tier_id, block, requests, tiers, catalog):
    where = f"{where} [{tier_id}]"
    assert set(block) <= PROFILE_TIER_KEYS, f"{where}: unknown keys {set(block) - PROFILE_TIER_KEYS}"
    granted = resolve_config(tiers[tier_id], tiers).get("capabilities") or {}
    # A profile requests capabilities; the tier grants a subset. A tier block
    # may only narrow that grant, so it cannot exist for a tier that grants
    # none of what the profile requests.
    for cap in requests:
        assert granted.get(cap) not in (None, "none"), \
            f"{where}: tier grants no {cap!r}, block may not exceed the grant"
    for pkg in block.get("packages", []):
        assert isinstance(pkg, str) and pkg, where
    for m in block.get("models", []):
        assert isinstance(m.get("id"), str) and m["id"], f"{where}: model entry needs an id"
        if m["id"] in catalog:
            # Data duplicated from the catalog must not contradict it.
            for k in ("quant", "file_mb", "ram_peak_mb"):
                if k in m:
                    assert m[k] == catalog[m["id"]][k], \
                        f"{where}: {m['id']}.{k} = {m[k]} contradicts catalog {catalog[m['id']][k]}"
    if "llama_server" in block:
        ls = block["llama_server"]
        assert set(ls) <= {"ctx"}, f"{where}: llama_server keys {set(ls)}"
        ctx = ls["ctx"]
        assert isinstance(ctx, int) and ctx > 0, where
        tier_ctx = max(m["ctx"] for m in resolve_config(tiers[tier_id], tiers)["models"])
        assert ctx <= tier_ctx, \
            f"{where}: ctx {ctx} exceeds the tier's maximum {tier_ctx} (narrow, never exceed)"
