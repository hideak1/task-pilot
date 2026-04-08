"""Task Pilot CLI entry point."""

import click

from task_pilot import launcher


@click.group()
def main():
    """Task Pilot — Claude Code session dispatcher panel."""
    pass


@main.command()
def ui():
    """Bootstrap or attach to the task-pilot tmux session."""
    launcher.main()


@main.command()
def kill():
    """Kill the task-pilot tmux session and everything inside it."""
    launcher.cmd_kill()
