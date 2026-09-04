"""The AI is told what it is: the web UI gets it as its default system
message, the terminal chat as the first message (test_chatterm)."""
import json

from ai2 import persona


def test_system_prompt_names_ai2_and_the_model_and_stays_short():
    text = persona.system_prompt("Qwen2.5 0.5B Instruct")
    assert "AI-2" in text and "Qwen2.5 0.5B Instruct" in text
    assert "offline" in text and "cannot browse" in text
    assert len(text.split()) < 120, "a long prompt confuses the small models and eats the context"


def test_ui_config_args_carry_the_web_ui_key():
    args = persona.ui_config_args("hi")
    assert args[0] == "--ui-config"
    assert json.loads(args[1]) == {"systemMessage": "hi"}
