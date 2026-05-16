def embed_prompt_metadata(
    prompt: str,
    job_id: str | None,
    user_id: str | None,
    user_name: str | None = None,
) -> str:
    if not job_id and not user_id and not user_name:
        return prompt
    lines = ["[METADATA]"]
    if job_id:
        lines.append(f"job_id: {job_id}")
    if user_id:
        lines.append(f"user_id: {user_id}")
    if user_name:
        lines.append(f"user_name: {user_name}")
    lines.append("[/METADATA]")
    lines.append("")
    lines.append(prompt)
    return "\n".join(lines)
