"""
Script to render to terminal, the changelog entry for the latest version in markdown so it can be copied and pasted for a GitHub release.

It requires pandoc to be installed on your system.
"""

import subprocess

res = subprocess.run(['pandoc', '--wrap=none', '-t', 'markdown_strict', str(Path(__file__).parent.parent / "CHANGELOG.rst")], capture_output=True)
print(res.stdout.decode('ascii').split('\n# ')[0])
