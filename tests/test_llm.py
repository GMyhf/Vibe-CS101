import io
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

from vibe_cs101 import llm
from vibe_cs101.config import LLMConfig
from vibe_cs101.llm import LLMError, _format_http_error, _open, _stream_chunk_content

CFG = LLMConfig(base_url="https://api.example.com/v1/", api_key="key", model="model-x")


class RetryTests(unittest.TestCase):
    def _req(self):
        return urllib.request.Request("https://api.example.com/v1/chat/completions")

    def test_transient_url_error_is_retried_once(self):
        calls = []

        def fake_urlopen(req, timeout=None):
            calls.append(1)
            if len(calls) == 1:
                raise urllib.error.URLError("nodename nor servname provided")
            return io.BytesIO(b"{}")

        with patch.object(llm.urllib.request, "urlopen", fake_urlopen), \
             patch.object(llm.time, "sleep") as sleep:
            resp = _open(self._req())
        self.assertEqual(len(calls), 2)
        self.assertEqual(resp.read(), b"{}")
        sleep.assert_called_once()

    def test_second_failure_propagates(self):
        with patch.object(
            llm.urllib.request, "urlopen", side_effect=urllib.error.URLError("dns down")
        ) as urlopen, patch.object(llm.time, "sleep"):
            with self.assertRaises(urllib.error.URLError):
                _open(self._req())
        self.assertEqual(urlopen.call_count, 2)

    def test_http_error_is_not_retried(self):
        err = urllib.error.HTTPError("u", 500, "boom", {}, io.BytesIO(b""))
        with patch.object(llm.urllib.request, "urlopen", side_effect=err) as urlopen:
            with self.assertRaises(urllib.error.HTTPError):
                _open(self._req())
        self.assertEqual(urlopen.call_count, 1)

    def test_network_error_message_names_endpoint(self):
        with patch.object(
            llm.urllib.request, "urlopen", side_effect=urllib.error.URLError("dns down")
        ), patch.object(llm.time, "sleep"):
            with self.assertRaises(LLMError) as ctx:
                llm.chat(CFG, [{"role": "user", "content": "hi"}])
        self.assertIn("model-x @ https://api.example.com/v1", str(ctx.exception))
        with patch.object(
            llm.urllib.request, "urlopen", side_effect=urllib.error.URLError("dns down")
        ), patch.object(llm.time, "sleep"):
            with self.assertRaises(LLMError) as ctx:
                list(llm.stream_chat(CFG, [{"role": "user", "content": "hi"}]))
        self.assertIn("model-x @ https://api.example.com/v1", str(ctx.exception))


class StreamChunkTests(unittest.TestCase):
    def test_normal_delta_content(self):
        data = '{"choices":[{"delta":{"content":"你好"}}]}'
        self.assertEqual(_stream_chunk_content(data), "你好")

    def test_empty_choices_usage_chunk_is_skipped(self):
        data = '{"object":"chat.completion.chunk","choices":[],"usage":{"total_tokens":3098}}'
        self.assertIsNone(_stream_chunk_content(data))

    def test_delta_without_content(self):
        data = '{"choices":[{"delta":{"role":"assistant"}}]}'
        self.assertIsNone(_stream_chunk_content(data))

    def test_invalid_json_raises(self):
        with self.assertRaises(LLMError):
            _stream_chunk_content("not json")


class LLMErrorFormattingTests(unittest.TestCase):
    def test_http_error_includes_resolved_endpoint(self):
        cfg = LLMConfig(base_url="https://api.example.com/v1/", api_key="key", model="model-x")

        message = _format_http_error(cfg, 401, '{"error":"bad key"}')

        self.assertIn("401", message)
        self.assertIn("model-x @ https://api.example.com/v1", message)
        self.assertIn("bad key", message)

    def test_403_1010_error_mentions_env_diagnostics(self):
        cfg = LLMConfig(base_url="https://api.openai.com/v1", api_key="key", model="gpt-4o-mini")

        message = _format_http_error(cfg, 403, "error code: 1010")

        self.assertIn("error code 1010", message)
        self.assertIn("python3 -m vibe_cs101 info", message)
        self.assertIn("vibe-cs101/.env", message)

    def test_524_error_mentions_upstream_timeout(self):
        cfg = LLMConfig(base_url="https://proxy.example.com/v1", api_key="key", model="gpt-5.5")

        message = _format_http_error(cfg, 524, "error code: 524")

        self.assertIn("上游 LLM 网关超时", message)
        self.assertIn("本地服务仍可用", message)


if __name__ == "__main__":
    unittest.main()
