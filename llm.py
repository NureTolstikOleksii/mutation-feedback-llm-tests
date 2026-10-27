"""
Виклик LLM через OpenAI-сумісний API (Groq)..

Налаштування беруться зі змінних середовища або файлу .env поруч зі скриптом:
  LLM_API_KEY   - ключ API
  LLM_BASE_URL  - напр. https://api.groq.com/openai/v1
  LLM_MODEL     - напр. openai/gpt-oss-20b
  LLM_REASONING_EFFORT - (необов'язково) low / medium / high для моделей з міркуваннями
  LLM_MAX_TOKENS       - (необов'язково) ліміт токенів відповіді, за замовчуванням 4000
"""
import json
import os
import random
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))


def load_env():
    path = os.path.join(HERE, ".env")
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


class LLM:
    def __init__(self, temperature=0.7, max_tokens=None, min_interval=2.0):
        load_env()
        self.key = os.environ.get("LLM_API_KEY", "")
        self.base = os.environ.get("LLM_BASE_URL", "https://api.groq.com/openai/v1").rstrip("/")
        self.model = os.environ.get("LLM_MODEL", "openai/gpt-oss-20b")
        self.reasoning_effort = os.environ.get("LLM_REASONING_EFFORT", "").strip()
        self.temperature = temperature
        self.max_tokens = max_tokens or int(os.environ.get("LLM_MAX_TOKENS", "4000"))
        self.min_interval = min_interval
        self._last = 0.0
        if not self.key:
            raise SystemExit("LLM_API_KEY is not set (see README, step 4).")

    def chat(self, messages):
        """Повертає (текст відповіді, usage dict)."""
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        if self.reasoning_effort:
            payload["reasoning_effort"] = self.reasoning_effort
        body = json.dumps(payload).encode("utf-8")
        for attempt in range(8):
            wait = self.min_interval - (time.time() - self._last)
            if wait > 0:
                time.sleep(wait)
            req = urllib.request.Request(
                self.base + "/chat/completions", data=body, method="POST",
                headers={"Authorization": f"Bearer {self.key}",
                         "Content-Type": "application/json",
                         "User-Agent": "mutation-pilot/1.0"},
            )
            try:
                self._last = time.time()
                with urllib.request.urlopen(req, timeout=120) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                choice = data["choices"][0]
                text = choice["message"].get("content") or ""
                if not text.strip() and choice.get("finish_reason") == "length":
                    print("  [warning] response truncated by token limit; increase LLM_MAX_TOKENS")
                return text, data.get("usage", {})
            except urllib.error.HTTPError as e:
                detail = e.read().decode("utf-8", "replace")[:300]
                if e.code in (429, 500, 502, 503, 504):
                    retry = e.headers.get("retry-after")
                    delay = float(retry) if retry and retry.replace(".", "").isdigit() else 5 * 2 ** attempt
                    delay = min(delay, 120) + random.random()
                    print(f"  [API {e.code}] retrying in {delay:.0f} s")
                    time.sleep(delay)
                    continue
                raise SystemExit(f"API error {e.code}: {detail}")
            except urllib.error.URLError as e:
                delay = 5 * 2 ** attempt
                print(f"  [network: {e.reason}] retrying in {delay} s")
                time.sleep(delay)
        raise SystemExit("API did not respond after several attempts.")