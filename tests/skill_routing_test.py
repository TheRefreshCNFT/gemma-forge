import unittest

import chat.server as server


def fake_skills():
    return {
        key: {
            "name": key,
            "key": key,
            "source": "harness",
            "description": "",
            "keywords": [],
        }
        for key in server.CORE_HARNESS_SKILL_KEYS
    }


class SkillRoutingTest(unittest.TestCase):
    def assert_routes(self, prompt, expected, unexpected=()):
        selected = server.resolve_skill_selection({"project": prompt, "messages": []}, fake_skills())
        for key in expected:
            self.assertIn(key, selected, f"{prompt!r} should select {key}; got {selected}")
        for key in unexpected:
            self.assertNotIn(key, selected, f"{prompt!r} should not select {key}; got {selected}")

    def test_simple_content_does_not_stage_code_intelligence(self):
        self.assert_routes(
            "Create a short markdown checklist for packing lunch.",
            expected=[],
            unexpected=["socraticode", "axon"],
        )

    def test_ui_ux_routes_visual_interface_work_without_code_graph_tools(self):
        self.assert_routes(
            "Design a responsive SaaS dashboard with charts, empty states, loading states, and accessible typography.",
            expected=["ui-ux-pro-max"],
            unexpected=["socraticode", "axon", "code-writer"],
        )

    def test_logo_generator_routes_brand_mark_work(self):
        self.assert_routes(
            "Create 6 distinct SVG logo concepts and a showcase page for a new AI product.",
            expected=["logo-generator"],
            unexpected=["socraticode", "axon"],
        )

    def test_code_writer_routes_runnable_code_work(self):
        self.assert_routes(
            "Write a Python CLI that parses a CSV, validates rows, and includes a unit test.",
            expected=["code-writer"],
            unexpected=["socraticode", "axon"],
        )
        self.assert_routes(
            "Build an HTML/CSS/JS single page app with local validation.",
            expected=["code-writer"],
        )

    def test_scrapling_routes_advanced_browser_scraping(self):
        self.assert_routes(
            "Crawl this dynamic website with JavaScript rendering, adaptive selectors, and Cloudflare Turnstile bypass.",
            expected=["scrapling-official"],
            unexpected=["socraticode", "axon", "code-writer"],
        )
        self.assert_routes(
            "Do deep research, data mining, and source harvesting across public websites for a market brief.",
            expected=["scrapling-official"],
            unexpected=["socraticode", "axon", "code-writer"],
        )

    def test_human_phrases_route_to_matching_skills(self):
        self.assert_routes(
            "Make this product page look professional, polished, and mobile friendly.",
            expected=["ui-ux-pro-max"],
            unexpected=["socraticode", "axon"],
        )
        self.assert_routes(
            "Create a clean brand symbol and app icon for the tool.",
            expected=["logo-generator"],
            unexpected=["socraticode", "axon"],
        )
        self.assert_routes(
            "Make a little command line utility that processes files and validates data.",
            expected=["code-writer"],
            unexpected=["socraticode", "axon"],
        )
        self.assert_routes(
            "Pull text from scanned documents and make the PDF searchable.",
            expected=["pdf"],
            unexpected=["socraticode", "axon"],
        )
        self.assert_routes(
            "Expose this API as agent tools with a local tool server.",
            expected=["mcp-builder"],
            unexpected=["socraticode", "axon"],
        )
        self.assert_routes(
            "Find in this repo where uploads are handled and explain the relevant files.",
            expected=["socraticode"],
            unexpected=["axon"],
        )
        self.assert_routes(
            "What breaks if I rename validate_user? Trace dependencies and affected tests.",
            expected=["axon"],
        )
        self.assert_routes(
            "Break down the work into milestones, tasks, and acceptance checks.",
            expected=["gsd"],
            unexpected=["socraticode", "axon"],
        )
        self.assert_routes(
            "Orient on repo state and take a pre edit backup before editing.",
            expected=["webot-flow"],
        )

    def test_socraticode_routes_semantic_codebase_discovery(self):
        self.assert_routes(
            "Use semantic codebase search to find where auth middleware lives and identify the relevant files.",
            expected=["socraticode"],
            unexpected=["axon"],
        )
        self.assert_routes(
            "Do a detailed search across this repo and find where auth lives.",
            expected=["socraticode"],
            unexpected=["scrapling-official", "axon"],
        )

    def test_axon_routes_structural_graph_and_impact_work(self):
        self.assert_routes(
            "Run impact analysis: what calls validate_user, what is the blast radius, and is there dead code?",
            expected=["axon"],
        )

    def test_advanced_codebase_request_can_select_socraticode_and_axon(self):
        self.assert_routes(
            "Map this codebase, find relevant files with semantic search, then run dependency graph blast radius analysis.",
            expected=["socraticode", "axon"],
        )

    def test_pdf_and_mcp_route_to_specific_skills(self):
        self.assert_routes(
            "OCR these scanned PDFs and generate a searchable PDF report.",
            expected=["pdf"],
        )
        self.assert_routes(
            "Build a FastMCP server with tool schemas, resources, pagination, auth, and actionable errors.",
            expected=["mcp-builder"],
        )

    def test_codex_global_skills_are_not_user_facing_by_default(self):
        skills = fake_skills()
        skills["firecrawl"] = {
            "name": "firecrawl",
            "key": "firecrawl",
            "source": "codex",
            "description": "Web scraper and content extractor.",
            "keywords": ["scrape", "crawl"],
        }
        selected = server.resolve_skill_selection(
            {"project": "scrape a dynamic website with stealth browser rendering", "messages": []},
            skills,
        )
        self.assertIn("scrapling-official", selected)
        self.assertNotIn("firecrawl", selected)


if __name__ == "__main__":
    unittest.main()
