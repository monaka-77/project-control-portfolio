# ProjectControl Portfolio

**Local-first task management CLI built with Python**

> This repository is a public portfolio edition of ProjectControl.  
> It contains only source code, tests, and fictional sample data. No production tasks, client information, personal paths, credentials, or operating data are included.

## Overview

ProjectControl is a Python CLI application for managing work across multiple projects with a focus on safe, traceable local operation.

It supports task creation, updates, status changes, completion, archiving, filtering, progress aggregation, JSON backups, CSV export, and a static HTML dashboard.

## Design focus

- **Local-first**: task data is stored in a local JSON file; no external API or package is required.
- **Safe file handling**: JSON writes use temporary files and atomic replacement where appropriate.
- **Validation**: status, priority, dates, and repository-relative output paths are validated.
- **Clear separation of responsibilities**: CLI, domain model, configuration, repository, service, and dashboard rendering are separated.
- **Testability**: tests use temporary directories and isolated sample data, preventing production-data changes.

## Feature set

- Create, view, update, complete, and archive tasks
- Filter by project, status, priority, tag, overdue, due-soon, and completion state
- Per-project progress and task summary
- Terminal dashboard and self-contained static HTML dashboard
- JSON backup and UTF-8 BOM CSV export
- Configuration-file validation
- Python standard library only

## Tech stack

- Python 3.13+
- Python standard library
- JSON
- `unittest`
- Git / GitHub

## Run locally

```powershell
$env:PYTHONPATH = "$PWD\src"
python -m project_control config
python -m project_control list
python -m project_control dashboard
python -m project_control dashboard-html --open
```

## Run tests

```powershell
$env:PYTHONPATH = "$PWD\src"
py -3.13 -m compileall src tests
py -3.13 -m unittest discover -s tests -v
```

## Sample data

The public edition includes fictional data at `examples/sample_tasks.json`. To try it locally, copy it to `data/tasks.json`:

```powershell
Copy-Item examples\sample_tasks.json data\tasks.json
```

## Repository structure

```text
.
├─ config/                  # Application configuration
├─ examples/                # Fictional sample data
├─ src/project_control/     # Application source
└─ tests/                   # Unit tests
```

## Portfolio scope

This repository demonstrates application design, validation, safe file operations, CLI implementation, static reporting, and unit testing. It is intentionally separated from the private operational repository so that real task data and business information remain private.
