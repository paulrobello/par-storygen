---
name: publish-story
description: Use when publishing a par-storygen exported story folder to pardev.net, updating the remote story index, or handling /skill:publish-story with an exported story path.
---

# Publish Story

Publish one exported par-storygen story folder to the pardev web host.

## Required input

The skill needs one argument: the local path to the exported story folder.

If no path is provided, ask the user for it before running anything. Do not guess or publish the current directory by default.

## Command

From this skill directory, run:

```bash
python3 scripts/publish_story.py /path/to/exported-story-folder
```

The script will:

1. Validate the path is a directory.
2. Create `root@lenny1.par-com.net:/docker/pardev/data/par-storygen/<folder-name>/`.
3. `rsync` the folder contents there.
4. Append a story link to `root@lenny1.par-com.net:/docker/pardev/data/par-storygen/index.html` if absent.
5. Open `https://pardev.net/par-storygen`.

## Quick reference

| Task | Command |
|---|---|
| Publish | `python3 ~/.pi/agent/skills/publish-story/scripts/publish_story.py /path/to/story` |
| Validate locally only | `python3 ~/.pi/agent/skills/publish-story/scripts/publish_story.py --dry-run /path/to/story` |
| Publish without opening browser | `python3 ~/.pi/agent/skills/publish-story/scripts/publish_story.py --no-open /path/to/story` |

## Notes

- The remote folder name is the basename of the local folder.
- Folder names must contain only letters, numbers, dots, underscores, and hyphens so SSH, rsync, HTML, and URLs stay unambiguous. Ask the user to rename the folder if validation rejects it.
- The public base URL is `https://pardev.net/par-storygen`.
- Don't push git changes as part of publishing — publishing and committing are separate actions the user controls independently.
