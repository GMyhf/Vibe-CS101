import json
import unittest

from vibe_cs101.mcp_server import _handle


class McpServerTests(unittest.TestCase):
    def test_initialize(self):
        resp = _handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        self.assertEqual(resp["id"], 1)
        self.assertEqual(resp["result"]["serverInfo"]["name"], "vibe-cs101")
        self.assertIn("tools", resp["result"]["capabilities"])

    def test_tools_list(self):
        resp = _handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        names = {t["name"] for t in resp["result"]["tools"]}
        self.assertEqual(names, {"search_materials", "read_section", "list_sources"})
        for tool in resp["result"]["tools"]:
            self.assertIn("inputSchema", tool)

    def test_tools_call_list_sources(self):
        resp = _handle(
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
             "params": {"name": "list_sources", "arguments": {}}}
        )
        text = resp["result"]["content"][0]["text"]
        self.assertIn("sources", json.loads(text))

    def test_unknown_method(self):
        resp = _handle({"jsonrpc": "2.0", "id": 4, "method": "bogus"})
        self.assertEqual(resp["error"]["code"], -32601)

    def test_notification_gets_no_response(self):
        self.assertIsNone(_handle({"jsonrpc": "2.0", "method": "notifications/initialized"}))


if __name__ == "__main__":
    unittest.main()
