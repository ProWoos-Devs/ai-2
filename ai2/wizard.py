"""The AI-2 setup wizard: the "scan this PC and give it an AI brain" walk-through.

Runs the engine chain a beginner should never have to type by hand:
detect -> tier -> tune (root) -> AI engine -> test model -> benchmark (AI Score)
-> recommendation -> model download -> how to use it. One step at a time, in
plain words, asking only what needs a human (apply the tuning? download?).

It is a terminal wizard on purpose: no extra dependency, works on the 2 GB
machines AI-2 targets, the root step (sudo) is transparent, and it is on-brand
(the logo is a terminal prompt). A graphical front end can reuse `Wizard` by
passing its own `ask`/`say`/`run` hooks; the step logic does not touch stdin
or stdout directly.

Started automatically at the first login of a fresh install (autostart entry
`ai2-setup.desktop` -> `ai2-first-boot` -> `ai-2 wizard`), and any time with
`ai-2 wizard`.
"""

from __future__ import annotations

import os
import subprocess
import sys
import urllib.request
from typing import Callable

from . import branding
from .backends import get_package_backend, get_service_backend
from .benchmark import STAR_LABELS, measure
from .detect import detect
from .models import load_catalog, recommend
from .runtime import (download_model, find_model_file, find_runtime, find_test_model,
                      model_dir, runtime_package)
from .state import load_score, mark_setup_done, write_score
from .tiers import assign, load_tiers, resolve_config
from .tuning import apply_plan, build_plan

INTERNET_PROBE = "https://huggingface.co"


def have_internet(url: str = INTERNET_PROBE, timeout: float = 5.0) -> bool:
    try:
        req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "ai-2"})
        with urllib.request.urlopen(req, timeout=timeout):
            return True
    except Exception:
        return False


def smallest_model(catalog: list[dict] | None = None) -> dict:
    """The catalog's smallest download: the standard benchmark model."""
    catalog = catalog or load_catalog()
    return min(catalog, key=lambda m: m["file_mb"])


def format_score(data: dict) -> str:
    score = data["ai_score"]
    bar = "#" * (score // 10) + "." * (10 - score // 10)
    lines = [f"AI Score   {score} / 100",
             f"           [{bar}]  {data['tg_tps']} tok/s generation, "
             f"{data['pp_tps']} tok/s prompt", "", "Good for:"]
    for key, label in STAR_LABELS.items():
        n = data["capabilities"][key]
        lines.append(f"  {'★' * n}{'☆' * (5 - n)}  {label}")
    return "\n".join(lines)


class Wizard:
    """The setup flow. `ask(question, default) -> bool`, `say(text)`,
    `run(cmd) -> returncode` are injectable so the flow can be driven by a
    test, a terminal, or a GUI. `yes=True` answers every question with its
    default (unattended)."""

    def __init__(self, ask: Callable[[str, bool], bool] | None = None,
                 say: Callable[[str], None] | None = None,
                 run: Callable[[list[str]], int] | None = None,
                 yes: bool = False):
        self.yes = yes
        self.say = say or (lambda text: print(text, flush=True))
        self._ask = ask or self._ask_terminal
        self.run = run or (lambda cmd: subprocess.run(cmd).returncode)
        self.report: dict = {"tuned": None, "score": None, "model": None, "completed": False}

    # -- I/O helpers ---------------------------------------------------------
    def ask(self, question: str, default: bool = True) -> bool:
        if self.yes:
            return default
        return self._ask(question, default)

    @staticmethod
    def _ask_terminal(question: str, default: bool) -> bool:
        hint = "[Y/n]" if default else "[y/N]"
        while True:
            try:
                answer = input(f"{question} {hint} ").strip().lower()
            except EOFError:
                return default
            if not answer:
                return default
            if answer in ("y", "yes", "s", "si", "sí", "j", "ja", "o", "oui"):
                return True
            if answer in ("n", "no", "nein", "non"):
                return False

    def head(self, n: int, title: str) -> None:
        self.say(f"\n{'─' * 66}\n Step {n}  {title}\n{'─' * 66}")

    def _sudo(self, argv: list[str]) -> int:
        """Run an ai-2 subcommand as root (directly if we are root)."""
        cmd = [sys.executable, "-m", "ai2.cli", *argv] if os.geteuid() == 0 else \
              ["sudo", "ai-2", *argv]
        return self.run(cmd)

    # -- the flow ------------------------------------------------------------
    def go(self) -> int:
        self.say(branding.compact())
        self.say("\nAI-2 setup: a few minutes, three questions, and this computer gets an AI brain.\n"
                 "You can stop at any time with Ctrl-C and run  ai-2 wizard  again later.")

        # 1. scan
        self.head(1, "What is this computer?")
        hw = detect()
        tiers = load_tiers()
        tier = assign(hw, tiers)
        config = resolve_config(tier, tiers)
        gpu = ", ".join(g.name for g in hw.gpus) or "none (the CPU does the AI work)"
        disk = {True: "spinning disk (HDD)", False: "solid state (SSD)", None: "unknown"}[hw.root_disk_rotational]
        self.say(f"  CPU     {hw.cpu_model} ({hw.logical_cores} cores, needs the '{hw.cpu_variant}' engine build)\n"
                 f"  RAM     {hw.ram_nominal_gib} GB\n"
                 f"  GPU     {gpu}\n"
                 f"  Disk    {disk}\n"
                 f"  Tier    {tier.label}: {hw.ram_nominal_gib} GB RAM and {hw.logical_cores} cores "
                 f"meet the {tier.label} floor ({tier.ram_gib} GB, {tier.cores} cores)")

        # 2. tune
        self.head(2, "Tune the system for this tier")
        try:
            backend = get_service_backend(hw.init_system)
            pkg_backend = get_package_backend()
            plan = build_plan(hw, tier, config, backend, pkg_backend)
        except ValueError as exc:
            plan = []
            self.say(f"  Cannot plan the tuning here ({exc}); skipping.")
        if plan:
            self.say("  AI-2 would:")
            for action in plan:
                self.say(f"    - {action.description}")
            if self.ask("  Apply this now? (asks for your password)", True):
                rc = 0
                if os.geteuid() == 0:
                    try:
                        apply_plan(plan)
                    except Exception as exc:
                        self.say(f"  Tuning failed: {exc}")
                        rc = 1
                else:
                    rc = self._sudo(["init", "--apply"])
                self.report["tuned"] = (rc == 0)
                self.say("  Done." if rc == 0 else "  Not applied (you can run  sudo ai-2 init --apply  later).")
            else:
                self.report["tuned"] = False
                self.say("  Skipped. Later:  sudo ai-2 init --apply")
        else:
            self.say("  Nothing to do for this tier.")

        # 3. engine
        self.head(3, "The AI engine")
        runtime_dir = find_runtime(hw.cpu_variant)
        if runtime_dir is None:
            pkg = runtime_package(hw.cpu_variant)
            self.say(f"  This CPU needs the '{hw.cpu_variant}' build of the engine (package {pkg}).")
            if self.ask("  Install it now? (asks for your password)", True):
                self._sudo(["runtime", "install", "--apply"])
                runtime_dir = find_runtime(hw.cpu_variant)
        if runtime_dir is None:
            self.say("  The engine is not installed, so AI-2 cannot measure this machine yet.\n"
                     "  Later:  sudo ai-2 runtime install --apply   then   ai-2 wizard")
            return self._early_exit()
        self.say(f"  Engine ready ({runtime_dir}).")

        # 4. a model to measure with
        self.head(4, "A first model")
        model_path = find_test_model()
        if model_path is None:
            small = smallest_model()
            self.say(f"  To measure the machine AI-2 needs a small model: {small['label']}, "
                     f"{small['file_mb']} MB to download.")
            if not have_internet():
                self.say("  No internet connection right now. Connect and run  ai-2 wizard  again,\n"
                         "  or:  ai-2 model pull " + small["id"])
                return self._early_exit()
            if self.ask("  Download it now?", True):
                try:
                    model_path = self._download(small)
                except Exception as exc:
                    self.say(f"  Download failed: {exc}. Later:  ai-2 model pull {small['id']}")
                    return self._early_exit()
            else:
                self.say(f"  Skipped. Later:  ai-2 model pull {small['id']}   then   ai-2 wizard")
                return self._early_exit()
        self.say(f"  Using {os.path.basename(model_path)}.")

        # 5. benchmark
        self.head(5, "Measure what this computer can really do")
        self.say("  Running the AI engine for real. On an old machine this takes a few minutes;\n"
                 "  the fan may spin up, that is normal.")
        try:
            data, rec = measure(hw, model_path, runtime_dir)
        except Exception as exc:
            self.say(f"  The measurement failed: {exc}\n  Later:  ai-2 benchmark")
            return self._early_exit()
        write_score(data)
        self.report["score"] = data["ai_score"]
        self.say("\n" + format_score(data))

        # 6. recommendation
        self.head(6, "The model that fits")
        local = rec["local"]
        if local is None:
            self.say("  No local model is a good fit for this machine; use a remote model instead.")
        else:
            self.say(f"  Recommended: {local['label']} ({local['params_b']}B, {local['quant']}), "
                     f"{rec['reason']}.")
            if rec["remote_suggested"]:
                self.say("  Anything larger is better used remotely from this machine.")
            self.report["model"] = local["id"]
            if find_model_file(local["file"]) is None:
                if have_internet() and self.ask(f"  Download it now ({local['file_mb']} MB)?", True):
                    try:
                        self._download(local)
                    except Exception as exc:
                        self.say(f"  Download failed: {exc}. Later:  ai-2 model pull {local['id']}")
                elif not have_internet():
                    self.say(f"  No internet right now. Later:  ai-2 model pull {local['id']}")
            else:
                self.say("  Already on this computer.")

        # 7. done
        self.head(7, "Ready")
        self.say("  To talk to the AI:   ai-2 chat        (or the 'AI-2 Chat' entry in the menu)\n"
                 "  For programs (API):  ai-2 serve       OpenAI-compatible, http://127.0.0.1:8080/\n"
                 "  This setup again:    ai-2 wizard\n"
                 "  The guide:           /usr/share/doc/ai2/START-HERE.txt")
        mark_setup_done()
        self.report["completed"] = True
        return 0

    def _download(self, model: dict) -> str:
        dest = model_dir()
        self.say(f"  Downloading {model['label']} ({model['file_mb']} MB) to {dest}/ ...")

        def progress(done, total):
            pct = f"{done * 100 // total:3d}%" if total else ""
            print(f"\r  {done // (1 << 20):5d} MB {pct}", end="", flush=True)

        path = download_model(model, dest, progress=progress)
        print()
        self.say(f"  Saved {path}")
        return path

    def _early_exit(self) -> int:
        """The flow stopped before the end. Ask whether to come back at login."""
        if self.ask("\nShow this setup again at the next login?", True):
            return 1
        mark_setup_done()
        return 1
