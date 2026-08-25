# Patch utilities for applying simplified unified diffs to existing field values.
# Shared helper for applying surgical configuration edits.

import html
import logging
import re
from dataclasses import dataclass
from typing import List

logger = logging.getLogger(__name__)

# Standard git unified-diff hunk header: "@@ -a,b +c,d @@[ optional section heading]".
# LLMs (e.g. GLM) emit these instead of the simplified "@@ <anchor>" format. The
# line numbers are unreliable, so we ignore them and locate the hunk by its
# context/±lines; only the trailing heading (if any) is kept as a soft anchor.
_GIT_HUNK_HEADER_RE = re.compile(
    r'^@@\s*-\d+(?:,\d+)?\s+\+\d+(?:,\d+)?\s*@@(?P<heading>.*)$'
)


@dataclass
class PatchChunk:
    """A single chunk of a patch, anchored by a context line."""
    context_anchor: str  # The @@ line content (used to locate position)
    old_lines: List[str]  # Lines prefixed with ' ' or '-' (what exists)
    new_lines: List[str]  # Lines prefixed with ' ' or '+' (what to write)


def _unescape_json_line(line: str) -> str:
    """Unescape JSON escape sequences in a line. The LLM sees config as JSON so it may write escaped quotes."""
    return line.replace('\\"', '"').replace('\\n', '\n').replace('\\\\', '\\')


def _normalize_line(line: str) -> str:
    """Normalize a line for fuzzy matching: strip whitespace, unescape HTML/JSON, and normalize unicode."""
    result = line.strip()
    # Unescape HTML entities (stored config may have &gt; &lt; &quot; &amp; etc.)
    result = html.unescape(result)
    # Unescape JSON-escaped sequences (LLM sees config as JSON with escaped quotes)
    result = _unescape_json_line(result)
    # Normalize smart quotes and other unicode to ASCII
    replacements = {
        '\u2018': "'", '\u2019': "'",  # Smart single quotes
        '\u201c': '"', '\u201d': '"',  # Smart double quotes
        '\u2014': '--',                 # Em dash
        '\u2013': '-',                  # En dash
        '\u2026': '...',               # Ellipsis
        '\u00a0': ' ',                 # Non-breaking space
    }
    for old, new in replacements.items():
        result = result.replace(old, new)
    return result


def _find_line_index(lines: List[str], target: str, start: int = 0) -> int:
    """Find a line in the content using 3-pass fuzzy matching.

    Returns the index of the matched line, or -1 if not found.
    Passes: exact → trimmed → normalized.
    """
    # Pass 1: Exact match
    for i in range(start, len(lines)):
        if lines[i] == target:
            return i

    # Attempt 2: right-trimmed match
    target_trimmed = target.rstrip()
    for i in range(start, len(lines)):
        if lines[i].rstrip() == target_trimmed:
            return i

    # Attempt 3: fully trimmed and normalized
    target_normalized = _normalize_line(target)
    for i in range(start, len(lines)):
        if _normalize_line(lines[i]) == target_normalized:
            return i

    return -1


def _match_line(content_line: str, seq_line: str) -> bool:
    """Check if a content line matches a sequence line using 3-pass fuzzy matching."""
    return (content_line == seq_line or
            content_line.rstrip() == seq_line.rstrip() or
            _normalize_line(content_line) == _normalize_line(seq_line))


def _find_sequence(lines: List[str], sequence: List[str], start: int = 0) -> tuple[int, int]:
    """Find a sequence of lines in the content using fuzzy matching.

    Tolerates blank lines in the source that don't appear in the sequence,
    since LLMs commonly omit blank lines in patches.

    Returns (start_index, span_length) or (-1, 0) if not found.
    Span may be larger than len(sequence) when blank lines were skipped.
    """
    if not sequence:
        return start, 0

    search_start = start
    while search_start < len(lines):
        first_idx = _find_line_index(lines, sequence[0], search_start)
        if first_idx == -1:
            return -1, 0

        # Try to match remaining sequence lines, skipping blank lines in source
        content_idx = first_idx + 1
        seq_idx = 1
        all_match = True
        while seq_idx < len(sequence) and content_idx < len(lines):
            if _match_line(lines[content_idx], sequence[seq_idx]):
                seq_idx += 1
                content_idx += 1
            elif lines[content_idx].strip() == '':
                # Skip blank lines in source that aren't in the sequence
                content_idx += 1
            else:
                all_match = False
                break

        if all_match and seq_idx == len(sequence):
            return first_idx, content_idx - first_idx

        search_start = first_idx + 1

    return -1, 0


def parse_patch_content(patch_text: str) -> List[PatchChunk]:
    """Parse simplified unified patch content into chunks.

    Expected format:
        *** Begin Patch
        @@ context anchor line
         unchanged line
        -removed line
        +added line
        @@ another anchor
         context
        -old
        +new
        *** End Patch
    """
    chunks: List[PatchChunk] = []

    # Find the patch envelope
    lines = patch_text.split('\n')
    start_idx = -1
    end_idx = len(lines)

    for i, line in enumerate(lines):
        if line.strip() == '*** Begin Patch':
            start_idx = i + 1
        elif line.strip() == '*** End Patch':
            end_idx = i
            break

    if start_idx == -1:
        # No envelope found — treat entire content as patch body
        start_idx = 0

    # Parse chunks delimited by @@ lines
    current_anchor = None
    current_old: List[str] = []
    current_new: List[str] = []

    for i in range(start_idx, end_idx):
        line = lines[i]
        if line.startswith('@@'):
            # Save previous chunk if exists
            if current_anchor is not None:
                chunks.append(PatchChunk(
                    context_anchor=current_anchor,
                    old_lines=current_old,
                    new_lines=current_new,
                ))
            # Start new chunk — anchor is everything after "@@" stripped
            anchor_text = line[2:].strip()
            git_header = _GIT_HUNK_HEADER_RE.match(line)
            if git_header:
                # Standard git hunk header: ignore the line numbers (LLMs get them
                # wrong), locate via the context/±lines that follow. The trailing
                # section heading, if any, is a soft anchor.
                current_anchor = git_header.group('heading').strip()
                current_old = []
            elif anchor_text.startswith('-'):
                # Simplified LLM format where the old line is embedded in the
                # anchor: "@@ -old_line" means the anchor IS the old line to replace.
                current_anchor = ''
                current_old = [anchor_text[1:]]  # Strip '-', treat as old line
            else:
                current_anchor = anchor_text
                current_old = []
            current_new = []
        elif current_anchor is not None or (current_old or current_new):
            if line.startswith('-'):
                current_old.append(line[1:])  # Strip the '-' prefix
            elif line.startswith('+'):
                current_new.append(_unescape_json_line(line[1:]))  # Strip '+' and unescape JSON
            elif line.startswith(' '):
                # Context line — present in both old and new
                current_old.append(line[1:])  # Strip the ' ' prefix
                current_new.append(_unescape_json_line(line[1:]))

    # Don't forget the last chunk
    if current_anchor is not None or current_old or current_new:
        chunks.append(PatchChunk(
            context_anchor=current_anchor or '',
            old_lines=current_old,
            new_lines=current_new,
        ))

    return chunks


def apply_patch(existing_value: str, patch_text: str) -> str:
    """Apply an simplified unified patch to an existing string value.

    Uses 3-pass fuzzy line matching (exact → trimmed → normalized)
    to locate edit positions.

    Args:
        existing_value: The current field value to patch
        patch_text: The raw patch content (including *** Begin/End Patch markers)

    Returns:
        The patched string value
    """
    chunks = parse_patch_content(patch_text)
    if not chunks:
        logger.warning("[Patch] No chunks parsed from patch content")
        return existing_value

    content_lines = existing_value.split('\n')
    cursor = 0  # Track position to apply patches in order

    for chunk in chunks:
        if chunk.context_anchor:
            # Find the context anchor in the content
            anchor_idx = _find_line_index(content_lines, chunk.context_anchor, cursor)
            if anchor_idx == -1:
                logger.warning(f"[Patch] Could not find context anchor: {chunk.context_anchor!r}")
                # Fall back: try to find old_lines directly from cursor
                anchor_idx = None
            else:
                cursor = anchor_idx + 1
        else:
            # Empty anchor — search from current cursor using old_lines directly
            anchor_idx = None

        search_start = cursor if anchor_idx is None else anchor_idx + 1

        if not chunk.old_lines:
            # Pure insertion after the anchor (or at cursor if no anchor)
            insert_at = search_start if anchor_idx is not None else cursor
            for j, new_line in enumerate(chunk.new_lines):
                content_lines.insert(insert_at + j, new_line)
            cursor = insert_at + len(chunk.new_lines)
        else:
            # Find the old_lines sequence
            seq_idx, span = _find_sequence(content_lines, chunk.old_lines, search_start)
            if seq_idx == -1 and anchor_idx is not None:
                # Try from the anchor itself (anchor might be part of old_lines context)
                seq_idx, span = _find_sequence(content_lines, chunk.old_lines, anchor_idx)
            if seq_idx == -1:
                # Last resort: search from cursor
                seq_idx, span = _find_sequence(content_lines, chunk.old_lines, cursor)

            if seq_idx == -1:
                logger.warning(f"[Patch] Could not find old lines sequence for chunk anchored at: {chunk.context_anchor!r}")
                continue

            # Replace old_lines span (may include skipped blank lines) with new_lines
            content_lines[seq_idx:seq_idx + span] = chunk.new_lines
            cursor = seq_idx + len(chunk.new_lines)

    return '\n'.join(content_lines)
