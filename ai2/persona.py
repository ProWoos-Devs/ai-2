"""What the AI is told about itself before the first message.

Without this the models answer "what can you do" with their vendor's
boilerplate ("I am a large language model trained by Google"), because
nothing ever told them where they are running. Found on rafaminu-pc
2026-09-04. One short paragraph on purpose: the small models get confused
by long instructions, and every token of it comes out of a 2048-token
context. The browser page gets it as the web UI's default system message
(llama-server --ui-config, applied on a browser's first visit; a browser
that already has saved chat settings keeps them), the terminal chat sends
it as the first message of every conversation."""

from __future__ import annotations

import json


def system_prompt(model_label: str = "a small language model", local: bool = True) -> str:
    where = ("running on this computer itself, offline; nothing the user writes leaves the machine"
             if local else
             "running on another computer that this one talks to over the network")
    return (
        "You are the assistant of AI-2, a Linux system that gives old computers an AI brain. "
        f"You are {model_label}, {where}. You can answer questions, explain things, write and "
        "improve text, summarize and translate. You cannot browse the internet, open files, "
        "see images or run commands. Answer briefly and plainly, in the language the user "
        "writes in. If you are not sure, say so."
    )


def ui_config_args(prompt: str) -> list[str]:
    """llama-server arguments that make `prompt` the web UI's default system
    message (key names from the web UI's settings-keys.ts, llama.cpp b10398)."""
    return ["--ui-config", json.dumps({"systemMessage": prompt})]
