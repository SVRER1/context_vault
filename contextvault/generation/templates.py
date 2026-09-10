SUMMARY_TEMPLATE = """
Generate a comprehensive summary for the topic: {topic}
Use the following context to generate the summary:
{context}

Requirements:
- Markdown format
- Include key points
- Include source citations
"""

STUDY_GUIDE_TEMPLATE = """
Create a structured study guide for the topic: {topic}
Context:
{context}

Requirements:
- Markdown format
- Sections, key concepts, examples
- Include source citations
"""

REVISION_NOTES_TEMPLATE = """
Create concise revision notes for the topic: {topic}
Context:
{context}

Requirements:
- Markdown format
- Bullet points
- Include source citations
"""

FLASHCARD_TEMPLATE = """
Generate {count} flashcards for the topic: {topic}
Context:
{context}

Requirements:
- Markdown format with Question/Answer structure
- Include source citations
"""

QUIZ_TEMPLATE = """
Generate a quiz with {count} questions for the topic: {topic}
Context:
{context}

Requirements:
- Markdown format
- Include answers at the end
- Include source citations
"""

TIMELINE_TEMPLATE = """
Create a chronological timeline for the topic: {topic}
Context:
{context}

Requirements:
- Markdown format
- Include source citations
"""

VAULT_REPORT_TEMPLATE = """
Create an overview of the vault contents focusing on: {topic}
Context:
{context}

Requirements:
- Markdown format
- Categories and key topics overview
- Include source citations
"""
