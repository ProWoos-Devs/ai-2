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
from .i18n import tr
from .models import (benchmark_model, best_present_model, is_starter, load_catalog,
                     models_that_fit, recommend)
from .runtime import (download_model, download_preflight, find_benchmark_model, find_model_file,
                      find_runtime, model_dir, runtime_package)
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
    lines = [tr("AI Score   {score} / 100").format(score=score),
             "           " + tr("[{bar}]  {tg} tok/s generation, {pp} tok/s prompt").format(
                 bar=bar, tg=data['tg_tps'], pp=data['pp_tps']),
             f"           {tr(data['feel']) if data.get('feel') else ''}", "", tr("Good for:")]
    for key, label in STAR_LABELS.items():
        n = data["capabilities"][key]
        lines.append(f"  {'★' * n}{'☆' * (5 - n)}  {tr(label)}")
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
        self.say(f"\n{'─' * 66}\n {tr('Step')} {n}  {tr(title)}\n{'─' * 66}")

    def _sudo(self, argv: list[str]) -> int:
        """Run an ai-2 subcommand as root (directly if we are root)."""
        cmd = [sys.executable, "-m", "ai2.cli", *argv] if os.geteuid() == 0 else \
              ["sudo", "ai-2", *argv]
        return self.run(cmd)

    # -- the flow ------------------------------------------------------------
    def go(self) -> int:
        self.say(branding.compact())
        self.say(tr("\nAI-2 setup: a few minutes, three questions, and this computer gets an AI brain.\n"
                    "You can stop at any time with Ctrl-C and run  ai-2 wizard  again later."))
        prev = self.previous_report()
        if prev:
            done = []
            if prev.get("tuned"):
                done.append(tr("tuning applied"))
            if prev.get("score") is not None:
                done.append(tr("AI Score {score}").format(score=prev['score']))
            if prev.get("model") and find_model_file(next((m["file"] for m in load_catalog() if m["id"] == prev["model"]), "")):
                done.append(tr("model {model} on disk").format(model=prev['model']))
            state = tr("completed") if prev.get("completed") else \
                tr("stopped at step {step}").format(step=prev.get('stopped_at') or '?')
            self.say(tr("Last run ({when}): {state}{done}. Steps already done are quick to pass through.")
                     .format(when=prev.get('when', '?'), state=state,
                             done=(", " + ", ".join(done)) if done else ""))

        # 1. scan
        self.head(1, "What is this computer?")
        hw = detect()
        tiers = load_tiers()
        tier = assign(hw, tiers)
        config = resolve_config(tier, tiers)
        gpu = ", ".join(g.name for g in hw.gpus) or tr("none (the CPU does the AI work)")
        disk = {True: tr("spinning disk (HDD)"), False: tr("solid state (SSD)"),
                None: tr("unknown")}[hw.root_disk_rotational]
        self.say(tr("  CPU     {cpu} ({cores} cores, needs the '{variant}' engine build)\n"
                    "  RAM     {ram} GB\n"
                    "  GPU     {gpu}\n"
                    "  Disk    {disk}\n"
                    "  Tier    {tier}: {ram} GB RAM and {cores} cores "
                    "meet the {tier} floor ({tier_ram} GB, {tier_cores} cores)")
                 .format(cpu=hw.cpu_model, cores=hw.logical_cores, variant=hw.cpu_variant,
                         ram=hw.ram_nominal_gib, gpu=gpu, disk=disk, tier=tier.label,
                         tier_ram=tier.ram_gib, tier_cores=tier.cores))

        # 2. tune
        self.head(2, "Tune the system for this tier")
        try:
            backend = get_service_backend(hw.init_system)
            pkg_backend = get_package_backend()
            plan = build_plan(hw, tier, config, backend, pkg_backend)
        except ValueError as exc:
            plan = []
            self.say(tr("  Cannot plan the tuning here ({exc}); skipping.").format(exc=exc))
        if plan:
            self.say(tr("  AI-2 would:"))
            for action in plan:
                self.say(f"    - {action.description}")
            if self.ask(tr("  Apply this now? (asks for your password)"), True):
                rc = 0
                if os.geteuid() == 0:
                    try:
                        apply_plan(plan)
                    except Exception as exc:
                        self.say(tr("  Tuning failed: {exc}").format(exc=exc))
                        rc = 1
                else:
                    rc = self._sudo(["init", "--apply"])
                self.report["tuned"] = (rc == 0)
                self.say(tr("  Done.") if rc == 0
                         else tr("  Not applied (you can run  sudo ai-2 init --apply  later)."))
            else:
                self.report["tuned"] = False
                self.say(tr("  Skipped. Later:  sudo ai-2 init --apply"))
        else:
            self.say(tr("  Nothing to do for this tier."))

        # 3. engine
        self.head(3, "The AI engine")
        runtime_dir = find_runtime(hw.cpu_variant)
        if runtime_dir is None:
            pkg = runtime_package(hw.cpu_variant)
            self.say(tr("  This CPU needs the '{variant}' build of the engine (package {pkg}).")
                     .format(variant=hw.cpu_variant, pkg=pkg))
            if self.ask(tr("  Install it now? (asks for your password)"), True):
                self._sudo(["runtime", "install", "--apply"])
                runtime_dir = find_runtime(hw.cpu_variant)
        if runtime_dir is None:
            self.say(tr("  The engine is not installed, so AI-2 cannot measure this machine yet.\n"
                        "  Later:  sudo ai-2 runtime install --apply   then   ai-2 wizard"))
            return self._early_exit(3)
        self.say(tr("  Engine ready ({dir}).").format(dir=runtime_dir))

        # 4. a model, and the measurement
        self.head(4, "A first model and the measurement")
        catalog = load_catalog()
        ready = best_present_model(catalog, hw.ram_mib)     # already on disk (e.g. bundled on the ISO)
        if ready:
            self.say(tr("  A model is already here so you can start straight away: {label}.")
                     .format(label=ready['label']))
            if is_starter(ready):
                self.say(tr("  Honest note: it is a very small starter model. It answers quickly and\n"
                            "  reads well, but it can get facts and simple math wrong. Good for trying\n"
                            "  things out; for real work, a bigger model below."))
            self.report["model"] = ready["id"]
        bench = benchmark_model(catalog)
        bench_path = find_benchmark_model()
        if bench_path is None:
            # The AI Score is measured only on the fixed benchmark model, so it
            # compares across machines. Get it if we can; otherwise defer.
            if have_internet():
                self.say(tr("  To measure this machine AI-2 uses a fixed model ({label}, "
                            "{mb} MB). Downloading it ...")
                         .format(label=bench['label'], mb=bench['file_mb']))
                try:
                    bench_path = self._download(bench)
                except Exception as exc:
                    self.say(tr("  Download failed: {exc}.").format(exc=exc))
            else:
                self.say(tr("  No internet right now (or a network login page is in the way)."))
                if ready:
                    self.say(tr("  You can already chat: ai-2 chat. The measurement and the best-fitting model\n"
                                "  come as soon as you are online; AI-2 will fetch {label} then.")
                             .format(label=bench['label']))
                    bigger = [m for m in models_that_fit(hw.ram_mib, catalog)
                              if m["params_b"] > ready["params_b"]]
                    if bigger:
                        self.say(tr("  Going by its {ram} GB RAM, this computer can also run "
                                    "(how fast, the measurement will tell):")
                                 .format(ram=hw.ram_nominal_gib))
                        for m in bigger[:3]:
                            self.say(tr("    - {label} ({mb} MB):  ai-2 model pull {id}")
                                     .format(label=m['label'], mb=m['file_mb'], id=m['id']))
                else:
                    self.say(tr("  Everything else is set up. Later, online:  ai-2 wizard  (fetches {label})")
                             .format(label=bench['label']))
                self.report["pending"].append("score")

        # 5. benchmark (only on the fixed model)
        rec = None
        if bench_path:
            self.head(5, "Measure what this computer can really do")
            self.say(tr("  Running the AI engine for real. On an old machine this takes a few minutes;\n"
                        "  the fan may spin up, that is normal."))
            try:
                data, rec = measure(hw, bench_path, runtime_dir)
                write_score(data)
                self.report["score"] = data["ai_score"]
                self.say("\n" + format_score(data))
            except Exception as exc:
                self.say(tr("  The measurement failed: {exc}\n  Later:  ai-2 benchmark").format(exc=exc))
                self.report["pending"].append("score")

        # 6. the model that fits (needs a score)
        if rec is not None:
            self.head(6, "The model that fits")
            local = rec["local"]
            if local is None:
                self.say(tr("  No local model is a good fit for this machine; use a remote model instead."))
            else:
                self.say(tr("  Best fit: {label} ({params}B, {quant}), {reason}.")
                         .format(label=local['label'], params=local['params_b'],
                                 quant=local['quant'], reason=rec['reason']))
                if rec["remote_suggested"]:
                    self.say(tr("  Anything larger is better used remotely from this machine."))
                self.report["model"] = local["id"]
                if find_model_file(local["file"]) is None:
                    if have_internet() and self.ask(
                            tr("  Download it now ({mb} MB)?").format(mb=local['file_mb']), True):
                        try:
                            self._download(local)
                        except Exception as exc:
                            self.say(tr("  Download failed: {exc}. Later:  ai-2 model pull {id}")
                                     .format(exc=exc, id=local['id']))
                    elif not have_internet():
                        self.say(tr("  No internet right now. Later:  ai-2 model pull {id}")
                                 .format(id=local['id']))
                else:
                    self.say(tr("  Already on this computer."))

        return self._finish(hw)

    def _finish(self, hw) -> int:
        """Step 7. Explain the setup, note anything pending, and check for
        updates while online."""
        pending = self.report["pending"]
        self.head(7, "Ready" if not pending else "Almost ready")
        if pending:
            self.say(tr("  Waiting for internet:"))
            if "score" in pending:
                self.say(tr("    - the AI Score and the best-fitting model:  ai-2 wizard  (once online)"))
            if "model" in pending:
                self.say(tr("    - the first model:  ai-2 model pull   then   ai-2 wizard"))
        # On the low-end tiers (on-demand runtime = RAM is tight) the terminal
        # chat is the recommendation: same AI, no browser eating memory next
        # to the model.
        tiers = load_tiers()
        config = resolve_config(assign(hw, tiers), tiers)
        if (config.get("runtime") or {}).get("service") == "on-demand":
            self.say(tr("  To talk to the AI:   ai-2 chat --terminal   (recommended on this machine: fastest, lightest)\n"
                        "  In the browser:      ai-2 chat              (or the 'AI-2 Chat' entry in the menu)\n"
                        "  For programs (API):  ai-2 serve             OpenAI-compatible, http://127.0.0.1:8080/\n"
                        "  This setup again:    ai-2 wizard\n"
                        "  More programs:       ai-2 install           (or 'Add/Remove Software' in the menu)\n"
                        "  Update everything:   ai-2 update            (or 'Software Updates' in the menu)\n"
                        "  The guide:           ai-2 guide             (or 'AI-2 Guide' in the menu)"))
        else:
            self.say(tr("  To talk to the AI:   ai-2 chat              (browser; or the 'AI-2 Chat' entry in the menu)\n"
                        "  In the terminal:     ai-2 chat --terminal   (lightest, works over SSH)\n"
                        "  For programs (API):  ai-2 serve             OpenAI-compatible, http://127.0.0.1:8080/\n"
                        "  This setup again:    ai-2 wizard\n"
                        "  More programs:       ai-2 install           (or 'Add/Remove Software' in the menu)\n"
                        "  Update everything:   ai-2 update            (or 'Software Updates' in the menu)\n"
                        "  The guide:           ai-2 guide             (or 'AI-2 Guide' in the menu)"))
        # Updates: the system and the model catalog can move on; check now if online.
        if have_internet():
            self._check_updates()
        else:
            self.say(tr("\n  When you are online, AI-2 checks for updates; you can also run  ai-2 update  any time."))
        if pending:
            self.report["stopped_at"] = 4
            self._save_report()
            if self.ask(tr("\nShow this setup again at the next login?"), True):
                return 1
            mark_setup_done()
            return 1
        mark_setup_done()
        self.report["completed"] = True
        self._save_report()
        return 0

    def _check_updates(self) -> None:
        """Tell the user, in one line, whether system updates are waiting. The
        AI-2 tool, the engine and the model catalog all update through pacman."""
        import shutil
        if not shutil.which("checkupdates"):
            self.say(tr("\n  Updates: keep AI-2 (and its models list) current with  ai-2 update"))
            return
        try:
            out = subprocess.run(["checkupdates"], capture_output=True, text=True, timeout=60).stdout
        except (OSError, subprocess.SubprocessError):
            out = ""
        n = len([ln for ln in out.splitlines() if ln.strip()])
        if n:
            self.say(tr("\n  Updates: {n} available (AI-2, the engine and the models list update this way).\n"
                        "           Install them with:  ai-2 update").format(n=n))
        else:
            self.say(tr("\n  Updates: the system is current. Check any time with  ai-2 update"))

    def _download(self, model: dict) -> str:
        dest = model_dir()
        problem = download_preflight(model, dest)
        if problem:
            raise RuntimeError(problem)
        self.say(tr("  Downloading {label} ({mb} MB) to {dest}/ ...")
                 .format(label=model['label'], mb=model['file_mb'], dest=dest))

        # one full line per 10% step, never a \r repaint: screen readers only
        # follow completed lines (accessibility plan P1.4)
        last_step = [-1]

        def progress(done, total):
            step = done * 10 // total if total else 0
            if step > last_step[0]:
                last_step[0] = step
                pct = f"{done * 100 // total:3d}%" if total else ""
                print(f"  {done // (1 << 20):5d} MB {pct}", flush=True)

        path = download_model(model, dest, progress=progress)
        self.say(tr("  Saved {path}").format(path=path))
        return path

    def _early_exit(self, step: int) -> int:
        """The flow stopped before the end. Ask whether to come back at login."""
        self.report["stopped_at"] = step
        self._save_report()
        if self.ask(tr("\nShow this setup again at the next login?"), True):
            return 1
        mark_setup_done()
        return 1
