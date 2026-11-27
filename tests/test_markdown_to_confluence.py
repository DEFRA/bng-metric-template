"""The Markdown to Confluence storage converter that publishes the
specification. Its cases follow those of the backend's converter, of which it
is a port."""

import sys
import unittest

from tests import support

if str(support.TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(support.TOOLS_DIR))

import gpkg_spec  # noqa: E402
import publish_spec  # noqa: E402
from markdown_to_confluence import markdown_to_storage  # noqa: E402


class MarkdownToStorageTest(unittest.TestCase):

    def test_headings_at_their_level(self):
        self.assertEqual("<h1>Spec</h1>", markdown_to_storage("# Spec"))
        self.assertEqual("<h3><code>Red Line Boundary</code></h3>",
                         markdown_to_storage("### `Red Line Boundary`"))

    def test_a_blockquote_of_several_lines_is_one_paragraph(self):
        self.assertEqual("<blockquote><p>line one line two</p></blockquote>",
                         markdown_to_storage("> line one\n> line two"))

    def test_inline_code_links_and_bold(self):
        self.assertEqual(
            '<p>See <a href="https://x/b.json"><code>b.json</code></a>'
            ' now</p>',
            markdown_to_storage("See [`b.json`](https://x/b.json) now"))
        self.assertEqual(
            "<p><strong>May be blank</strong>: no</p>",
            markdown_to_storage("**May be blank**: no"))

    def test_a_table_has_header_and_body_cells(self):
        markdown = "| Column | Type |\n| --- | --- |\n| `fid` | `INTEGER` |"
        self.assertEqual(
            "<table><tbody><tr><th>Column</th><th>Type</th></tr>"
            "<tr><td><code>fid</code></td><td><code>INTEGER</code></td></tr>"
            "</tbody></table>",
            markdown_to_storage(markdown))

    def test_angle_brackets_and_ampersands_are_escaped(self):
        self.assertIn("<td><code>a &lt;&gt; &amp; b</code></td>",
                      markdown_to_storage("| x |\n| --- |\n| `a <> & b` |"))

    def test_an_escaped_pipe_stays_in_its_cell(self):
        self.assertEqual(
            "<table><tbody><tr><th>Rule</th></tr><tr><td>a | b</td></tr>"
            "</tbody></table>",
            markdown_to_storage("| Rule |\n| --- |\n| a \\| b |"))

    def test_a_list_item_continues_on_an_indented_line(self):
        self.assertEqual("<ul><li>first line second line</li></ul>",
                         markdown_to_storage("- first line\n  second line"))

    def test_the_published_page_carries_the_banner_and_the_specification(self):
        markdown = gpkg_spec.render_markdown(gpkg_spec.build_spec())
        body = publish_spec.storage_body(markdown)
        self.assertTrue(
            body.startswith('<ac:structured-macro ac:name="info">'))
        self.assertIn(
            "<h1>BNG Service template: GeoPackage specification</h1>", body)
        self.assertNotIn("| ---", body)

    def test_a_table_of_contents_comes_before_the_first_section(self):
        body = publish_spec.storage_body(
            "# Title\n\nIntroduction.\n\n## Section\n\n## Another")
        contents = body.index('<ac:structured-macro ac:name="toc">')
        self.assertLess(body.index("<p>Introduction.</p>"), contents)
        self.assertLess(contents, body.index("<h2>Section</h2>"))
        self.assertEqual(1, body.count('ac:name="toc"'))
        self.assertIn('<ac:parameter ac:name="minLevel">2</ac:parameter>',
                      body)
        self.assertIn('<ac:parameter ac:name="maxLevel">3</ac:parameter>',
                      body)


if __name__ == "__main__":
    unittest.main()
