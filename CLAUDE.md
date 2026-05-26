# Personal Projects

Personal repo for outside work and side projects — separate from Mission Lane's dbt-models work.

## Context

- **Owner**: Jay Park (`jayparkml`)
- **Purpose**: Personal experiments, side projects, learning, tools
- **Stack**: Varies by project — Python, TypeScript, or whatever fits the task

## Project Structure

Each project lives in its own subdirectory. When starting a new project, create a folder and include a brief note in that folder's README or `CLAUDE.md` about what it does.

## Guidelines

- All global agents, skills, and rules from `~/.claude/` apply here
- Default to clean, minimal implementations — no gold-plating
- Prefer standard tooling per language (uv/pip for Python, npm/bun for JS/TS)
- Keep secrets out of the repo — use `.env` files (already in `.gitignore`)
