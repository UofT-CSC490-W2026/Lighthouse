"""Prompt builders for wiki generation LLM calls."""

from __future__ import annotations

STRUCTURE_SYSTEM_PROMPT = """\
You are a technical documentation expert. Given a repository's file structure and \
representative code samples, generate a hierarchical wiki outline as JSON.

The JSON must conform to this schema:
{
  "title": "string — wiki title",
  "description": "string — one-paragraph summary of the repository",
  "sections": [
    {
      "title": "string",
      "slug": "string — URL-safe identifier",
      "pages": [
        {
          "title": "string",
          "slug": "string — URL-safe identifier",
          "description": "string — what this page should cover",
          "source_file_hints": ["string — relevant file paths"]
        }
      ],
      "subsections": []
    }
  ]
}

Guidelines:
- Create a logical hierarchy that helps someone new understand the codebase.
- Each page should focus on a single topic (a service, a module, a concept).
- Use clear, descriptive titles.
- Include source_file_hints so the page generator knows where to look.
- Keep the outline practical — aim for 5-15 pages total.
- Return ONLY valid JSON, no markdown fences or commentary.\
"""

PAGE_SYSTEM_PROMPT = """\
You are a technical documentation writer. Generate a wiki page in Markdown given \
the page title, description, and relevant code context from the repository.

Guidelines:
- Write clear, concise documentation aimed at developers.
- Include code snippets from the provided context where they clarify the explanation.
- Use headers (##, ###) to organize the page.
- Explain the "why" and "how", not just the "what".
- Reference specific files and functions when relevant.
- Keep the page focused on its stated topic.
- Do not invent code that isn't in the provided context.\
"""


def build_structure_prompt(
    file_paths: list[str],
    sample_chunks: list[str],
    repo_name: str,
) -> list[dict[str, str]]:
    """Build messages for the wiki structure generation LLM call."""
    file_tree = "\n".join(file_paths)
    samples = "\n\n---\n\n".join(sample_chunks)

    user_content = (
        f"Repository: {repo_name}\n\n"
        f"## File Structure\n```\n{file_tree}\n```\n\n"
        f"## Representative Code Samples\n{samples}"
    )

    return [
        {"role": "system", "content": STRUCTURE_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


def build_page_prompt(
    page_title: str,
    page_description: str,
    context_chunks: list[str],
) -> list[dict[str, str]]:
    """Build messages for a single wiki page generation LLM call."""
    context = "\n\n---\n\n".join(context_chunks) if context_chunks else "No code context available."

    user_content = (
        f"## Page: {page_title}\n\n"
        f"**Description:** {page_description}\n\n"
        f"## Relevant Code Context\n{context}"
    )

    return [
        {"role": "system", "content": PAGE_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]
