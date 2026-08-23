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
from .runtime import (download_model, download_preflight, find_model_file, find_runtime,
                      find_test_model, model_dir, runtime_package)
from .state import load_score, mark_setup_done, write_score
from . import serverstate
from .tiers import assign, load_tiers, resolve_config
from .tuning import apply_plan, build_plan

INTERNET_PROBE = "https://huggingface.co"


def have_internet(url: str = INTERNET_PROBE, timeout: float = 5.0) -> bool:
    """True when the probe host really answered (a captive portal that
    redirects every request to its login page counts as offline)."""
    from urllib.parse import urlparse
    try:
        req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "ai-2"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return urlparse(resp.url).hostname == urlparse(url).hostname
    except Exception:
        return False


def smallest_model(catalog: list[dict] | None = None) -> dict:
    """The standard benchmark model: the catalog entry flagged `benchmark`
    (every AI Score is measured on the same workload), else the smallest."""
    catalog = catalog or load_catalog()
    flagged = [m for m in catalog if m.get("benchmark")]
    return flagged[0] if flagged else min(catalog, key=lambda m: m["file_mb"])


def format_score(data: dict) -> str:
    score = data["ai_score"]
    bar = "#" * (score // 10) + "." * (10 - score // 10)
    lines = [f"AI Score   {score} / 100",
             f"           [{bar}]  {data['tg_tps']} tok/s generation, "
             f"{data['pp_tps']} tok/s prompt",
             f"           {data.get('feel', '')}", "", "Good for:"]
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
        self._say = say or (lambda text: print(text, flush=True))
        self._ask = ask or self._ask_terminal
        self.run = run or (lambda cmd: subprocess.run(cmd).returncode)
        self.report: dict = {"tuned": None, "score": None, "model": None, "completed": False,
                             "pending": [], "stopped_at": None}
        self._log = None
        try:
            os.makedirs(serverstate.state_dir(), exist_ok=True)
            self._log = open(os.path.join(serverstate.state_dir(), "wizard.log"), "a")
            import time
            self._log.write(f"\n===== ai-2 wizard {time.strftime('%Y-%m-%d %H:%M:%S')} =====\n")
        except OSError:
            self._log = None

    def say(self, text: str) -> None:
        """Show text and keep a transcript in the state dir (support questions
        can be answered from it; nothing personal is written)."""
        self._say(text)
        if self._log:
            try:
                self._log.write(text + "\n")
                self._log.flush()
            except OSError:
                pass

    @staticmethod
    def report_path() -> str:
        return os.path.join(serverstate.state_dir(), "wizard.json")

    def _save_report(self) -> None:
        import json
        import time
        try:
            os.makedirs(serverstate.state_dir(), exist_ok=True)
            with open(self.report_path(), "w") as fh:
                json.dump(self.report | {"when": time.strftime("%Y-%m-%d %H:%M")}, fh, indent=1)
        except OSError:
            pass

    @classmethod
    def previous_report(cls) -> dict | None:
        import json
        try:
            with open(cls.report_path()) as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return None

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
        prev = self.previous_report()
        if prev:
            done = []
            if prev.get("tuned"):
                done.append("tuning applied")
            if prev.get("score") is not None:
                done.append(f"AI Score {prev['score']}")
            if prev.get("model") and find_model_file(next((m["file"] for m in load_catalog() if m["id"] == prev["model"]), "")):
                done.append(f"model {prev['model']} on disk")
            state = "completed" if prev.get("completed") else f"stopped at step {prev.get('stopped_at') or '?'}"
            self.say(f"Last run ({prev.get('when', '?')}): {state}" + (f", {', '.join(done)}" if done else "")
                     + ". Steps already done are quick to pass through.")

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
            return self._early_exit(3)
        self.say(f"  Engine ready ({runtime_dir}).")

        # 4. a model to measure with
        self.head(4, "A first model")
        model_path = find_test_model()
        if model_path is None:
            small = smallest_model()
            self.say(f"  To measure the machine AI-2 needs a small model: {small['label']}, "
                     f"{small['file_mb']} MB to download.")
            if not have_internet():
                self.say("  No internet connection right now (or a network login page is in the way).\n"
                         f"  The download waits; everything else is set up. Later:  ai-2 model pull {small['id']}"
                         "   then   ai-2 wizard")
                self.report["pending"].append("model")
            elif self.ask("  Download it now?", True):
                try:
                    model_path = self._download(small)
                except Exception as exc:
                    self.say(f"  Download failed: {exc}. Later:  ai-2 model pull {small['id']}   then   ai-2 wizard")
                    self.report["pending"].append("model")
            else:
                self.say(f"  Skipped. Later:  ai-2 model pull {small['id']}   then   ai-2 wizard")
                self.report["pending"].append("model")
        if model_path is None:
            return self._finish(hw)
        self.say(f"  Using {os.path.basename(model_path)}.")

        # 5. benchmark
        self.head(5, "Measure what this computer can really do")
        self.say("  Running the AI engine for real. On an old machine this takes a few minutes;\n"
                 "  the fan may spin up, that is normal.")
        try:
            data, rec = measure(hw, model_path, runtime_dir)
        except Exception as exc:
            self.say(f"  The measurement failed: {exc}\n  Later:  ai-2 benchmark")
            return self._early_exit(5)
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

        return self._finish(hw)

    def _finish(self, hw) -> int:
        """Step 7. With nothing pending the setup is complete; with a pending
        model download it says what is left and asks whether to come back."""
        self.head(7, "Ready" if not self.report["pending"] else "Almost ready")
        if self.report["pending"]:
            self.say("  Not done yet (needs internet):\n"
                     "    - the first model and the AI Score:   ai-2 model pull   then   ai-2 wizard")
        self.say("  To talk to the AI:   ai-2 chat        (or the 'AI-2 Chat' entry in the menu)\n"
                 "  For programs (API):  ai-2 serve       OpenAI-compatible, http://127.0.0.1:8080/\n"
                 "  This setup again:    ai-2 wizard\n"
                 "  The guide:           /usr/share/doc/ai2/START-HERE.txt")
        if self.report["pending"]:
            self.report["stopped_at"] = 4
            self._save_report()
            if self.ask("\nShow this setup again at the next login?", True):
                return 1
            mark_setup_done()
            return 1
        mark_setup_done()
        self.report["completed"] = True
        self._save_report()
        return 0

    def _download(self, model: dict) -> str:
        dest = model_dir()
        problem = download_preflight(model, dest)
        if problem:
            raise RuntimeError(problem)
        self.say(f"  Downloading {model['label']} ({model['file_mb']} MB) to {dest}/ ...")

        def progress(done, total):
            pct = f"{done * 100 // total:3d}%" if total else ""
            print(f"\r  {done // (1 << 20):5d} MB {pct}", end="", flush=True)

        path = download_model(model, dest, progress=progress)
        print()
        self.say(f"  Saved {path}")
        return path

    def _early_exit(self, step: int) -> int:
        """The flow stopped before the end. Ask whether to come back at login."""
        self.report["stopped_at"] = step
        self._save_report()
        if self.ask("\nShow this setup again at the next login?", True):
            return 1
        mark_setup_done()
        return 1
