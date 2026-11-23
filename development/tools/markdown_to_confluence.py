"""Convert the generated specification's Markdown to Confluence storage format.

Confluence keeps a page as XHTML in its own dialect. This is a small
converter, not a Markdown engine: it handles what gpkg_spec.py writes, which
is headings, blockquotes, paragraphs, tables, bullet lists, and inline code,
links and bold. It is a port of scripts/markdown-to-confluence.mjs in
bng-metric-backend, which publishes the data dictionary the same way.
"""
import re

HEADING = re.compile(r"^(#{1,6})\s+(\S.*)$")
LIST_ITEM = re.compile(r"^[-*]\s+(\S.*)$")
SEPARATOR_CELL = re.compile(r"^:?-+:?$")
CONTINUATION = re.compile(r"^\s+\S")


def escape_html(value):
    return (value.replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


def escape_attribute(value):
    return escape_html(value).replace('"', "&quot;")


def split_table_row(line):
    """The cells of a table row, honouring the `\\|` escape for a pipe."""
    cells, current, index = [], "", 0
    while index < len(line):
        char = line[index]
        if char == "\\" and line[index + 1:index + 2] == "|":
            current += "|"
            index += 1
        elif char == "|":
            cells.append(current)
            current = ""
        else:
            current += char
        index += 1
    cells.append(current)
    return [value.strip() for value in cells[1:-1]]


def is_separator_row(line):
    trimmed = line.strip()
    if not trimmed.startswith("|"):
        return False
    cells = split_table_row(trimmed)
    return bool(cells) and all(SEPARATOR_CELL.match(value) for value in cells)


def is_table_start(lines, index):
    return (lines[index].strip().startswith("|")
            and index + 1 < len(lines) and is_separator_row(lines[index + 1]))


def match_link(text, start):
    close = text.find("]", start + 1)
    if close == -1 or text[close + 1:close + 2] != "(":
        return None
    url_end = text.find(")", close + 2)
    if url_end == -1:
        return None
    return text[start + 1:close], text[close + 2:url_end], url_end + 1


def match_token(text, index):
    """The inline token at `index`: (kind, payload, next index), or None."""
    char = text[index]
    if char == "`":
        end = text.find("`", index + 1)
        if end != -1:
            return "code", text[index + 1:end], end + 1
    elif char == "[":
        link = match_link(text, index)
        if link:
            label, url, after = link
            return "link", (label, url), after
    elif text.startswith("**", index):
        end = text.find("**", index + 2)
        if end != -1:
            return "bold", text[index + 2:end], end + 2
    return None


def render_inline(text):
    out, index = [], 0
    while index < len(text):
        token = match_token(text, index)
        if token is None:
            out.append(escape_html(text[index]))
            index += 1
            continue
        kind, payload, index = token
        if kind == "code":
            out.append(f"<code>{escape_html(payload)}</code>")
        elif kind == "link":
            label, url = payload
            out.append(f'<a href="{escape_attribute(url)}">'
                       f"{render_inline(label)}</a>")
        else:
            out.append(f"<strong>{render_inline(payload)}</strong>")
    return "".join(out)


def consume_blockquote(lines, start):
    quote, index = [], start
    while index < len(lines) and lines[index].startswith(">"):
        quote.append(re.sub(r"^>\s?", "", lines[index]))
        index += 1
    return (f"<blockquote><p>{render_inline(' '.join(quote))}</p>"
            "</blockquote>"), index


def render_row(cells, tag):
    inner = "".join(f"<{tag}>{render_inline(value)}</{tag}>"
                    for value in cells)
    return f"<tr>{inner}</tr>"


def consume_table(lines, start):
    header = split_table_row(lines[start].strip())
    index, body = start + 2, []
    while index < len(lines) and lines[index].strip().startswith("|"):
        body.append(render_row(split_table_row(lines[index].strip()), "td"))
        index += 1
    return (f"<table><tbody>{render_row(header, 'th')}{''.join(body)}"
            "</tbody></table>"), index


def consume_list(lines, start):
    items, current, index = [], None, start
    while index < len(lines) and lines[index].strip():
        item = LIST_ITEM.match(lines[index])
        if item:
            if current is not None:
                items.append(current)
            current = item.group(1).strip()
        elif CONTINUATION.match(lines[index]) and current is not None:
            current = f"{current} {lines[index].strip()}"
        else:
            break
        index += 1
    if current is not None:
        items.append(current)
    inner = "".join(f"<li>{render_inline(item)}</li>" for item in items)
    return f"<ul>{inner}</ul>", index


def is_paragraph_line(lines, index):
    line = lines[index]
    return (bool(line.strip()) and not HEADING.match(line)
            and not line.startswith(">") and not LIST_ITEM.match(line)
            and not is_table_start(lines, index))


def consume_paragraph(lines, start):
    paragraph, index = [], start
    while index < len(lines) and is_paragraph_line(lines, index):
        paragraph.append(lines[index].strip())
        index += 1
    return f"<p>{render_inline(' '.join(paragraph))}</p>", index


def consume_block(lines, index):
    line = lines[index]
    heading = HEADING.match(line)
    if heading:
        level = len(heading.group(1))
        return (f"<h{level}>{render_inline(heading.group(2).strip())}"
                f"</h{level}>"), index + 1
    if line.startswith(">"):
        return consume_blockquote(lines, index)
    if is_table_start(lines, index):
        return consume_table(lines, index)
    if LIST_ITEM.match(line):
        return consume_list(lines, index)
    return consume_paragraph(lines, index)


def markdown_to_storage(markdown):
    lines = markdown.replace("\r\n", "\n").split("\n")
    blocks, index = [], 0
    while index < len(lines):
        if not lines[index].strip():
            index += 1
            continue
        html, index = consume_block(lines, index)
        blocks.append(html)
    return "\n".join(blocks)
