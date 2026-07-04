import unittest

from vibe_cs101.config import LLMConfig
from vibe_cs101.llm import LLMError, _format_http_error, _stream_chunk_content


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


if __name__ == "__main__":
    unittest.main()
