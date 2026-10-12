Your AI-2 machine can serve its local model to programs, not just to the chat page. `ai-2 serve` starts llama.cpp's `llama-server` on demand with the recommended model and exposes an OpenAI-compatible API at:

```
http://127.0.0.1:8080
```

The server exits by itself when idle (how long is set by your [[tier|Capability Tiers]], 5 minutes on Tiny, 10 on Light), so a low-memory machine gets its RAM back. A chat page merely left open does not keep it alive. Stop it immediately with `ai-2 stop`.

## Using it

Any OpenAI-style client works by pointing its base URL at the server. For example:

```
curl http://127.0.0.1:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "Hello"}]}'
```

`ai-2 chat` uses this same server, it waits until the server reports ready (not just an open port, `llama-server` answers its health check while still loading a model on a slow disk) and opens the built-in web UI.

## From other devices

By default the API binds to localhost only. To use it from other machines on your network, an API key is required:

```
ai-2 serve --host 0.0.0.0 --api-key YOUR_KEY
```

Binding off localhost without a key is refused unless you explicitly pass `--insecure`.

`ai-2 serve` is a foreground command, and there is no boot-time service for it yet. A machine that serves other apps needs the command kept running, in tmux or screen, or in a runit service of your own. `ai-2 chat` only ever starts a server on localhost, without a key.

## Apps that can use it

Any app with a custom OpenAI-compatible base URL takes `http://HOST:8080/v1` plus the key you passed to `--api-key`. The following document such a field (documented by their upstreams as of 2026-09-14, not yet driven end to end from an AI-2 machine):

* Open WebUI: Settings, Admin, Connections, add an OpenAI API connection with the URL and key.
* Paperless-GPT: `LLM_PROVIDER=openai`, `OPENAI_BASE_URL=http://HOST:8080/v1`, `OPENAI_API_KEY`.
* Open Notebook: Settings, Models, OpenAI-compatible provider with the base URL and key (its embedding, speech-to-text and text-to-speech slots want their own endpoints, which AI-2 does not offer today).
* Blinko: the OpenAI provider entry with a custom API endpoint.
* Home Assistant: only through the community integrations Home LLM (Generic OpenAI backend) or Extended OpenAI Conversation (Base Url). Home Assistant's built-in OpenAI integration works only with the official OpenAI endpoint, its Ollama integration needs an Ollama server, and its Anthropic integration takes only an API key.

These apps run on another machine; the AI-2 machine is only the server. `/v1/models` reports the model file path as the model id. An embedding endpoint exists as well: `ai-2 serve --model nomic-embed-text-v2-moe --host 0.0.0.0 --api-key KEY` serves `/v1/embeddings` on port 8081 (it is the server `ai-2 doc` uses locally, see [[Commands]]).

Which machine can be the server is a question for the [[AI Score|AI Score and Benchmarks]], not the tier. On the 2011 reference laptop the 0.5B model generates at about 2 tokens per second and reads prompts no faster, so a 1000-token prompt takes minutes before the first output token. Machines like that are the clients: a stronger machine on the network runs `ai-2 serve` and they run `ai-2 chat --remote`. Background jobs such as document tagging tolerate a slow server, a voice assistant does not.

## Good to know

* `ai-2 serve` warns when free RAM is below the model's measured peak, before you find out the hard way.
* `ai-2 chat --model X` refuses to attach to a server that holds a different model.
* Context size defaults come from the applied tier (1024 tokens on Tiny).
* With no [[AI Score|AI Score and Benchmarks]] measured yet, `serve` and `chat` fall back to the best model already on disk, so a fresh machine works before its first benchmark.
