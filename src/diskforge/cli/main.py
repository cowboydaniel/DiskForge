"""
DiskForge CLI Main Entry Point.

Provides a comprehensive command-line interface for disk management operations.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
import humanize

from diskforge import __version__
from diskforge.core.config import DiskForgeConfig, load_config
from diskforge.core.models import FileSystem
from diskforge.core.safety import DangerMode
from diskforge.core.session import Session

console = Console()


def get_session(ctx: click.Context) -> Session:
    """Get or create session from context."""
    if "session" not in ctx.obj:
        config = ctx.obj.get("config") or load_config()
        ctx.obj["session"] = Session(config=config)
    return ctx.obj["session"]


@click.group()
@click.version_option(version=__version__, prog_name="DiskForge")
@click.option(
    "--config",
    "-c",
    type=click.Path(exists=True, path_type=Path),
    help="Path to configuration file",
)
@click.option(
    "--danger-mode",
    is_flag=True,
    help="Enable danger mode for destructive operations",
)
@click.option("--json", "json_output", is_flag=True, help="Output in JSON format")
@click.option("--quiet", "-q", is_flag=True, help="Suppress non-essential output")
@click.pass_context
def cli(
    ctx: click.Context,
    config: Path | None,
    danger_mode: bool,
    json_output: bool,
    quiet: bool,
) -> None:
    """
    DiskForge - Cross-platform disk management tool.

    A production-grade application for disk inventory, partition management,
    cloning, imaging, and rescue media creation.
    """
    ctx.ensure_object(dict)

    if config:
        ctx.obj["config"] = DiskForgeConfig.load(config)
    else:
        ctx.obj["config"] = load_config()

    ctx.obj["json_output"] = json_output
    ctx.obj["quiet"] = quiet

    if danger_mode:
        session = get_session(ctx)
        console.print("[yellow]⚠️  Danger mode requested[/yellow]")
        confirm = click.prompt(
            "Type 'I understand the risks' to enable danger mode",
            default="",
        )
        if session.enable_danger_mode(confirm):
            console.print("[red]Danger mode ENABLED[/red]")
        else:
            console.print("[red]Danger mode NOT enabled - incorrect confirmation[/red]")


@cli.command("list")
@click.option("--smart", is_flag=True, help="Include SMART health data")
@click.pass_context
def list_disks(ctx: click.Context, smart: bool) -> None:
    """List all disks and partitions."""
    session = get_session(ctx)
    json_output = ctx.obj.get("json_output", False)

    with console.status("Scanning disks..."):
        inventory = session.platform.get_disk_inventory()

    if json_output:
        import json

        click.echo(json.dumps(inventory.to_dict(), indent=2, default=str))
        return

    # Display disks table
    table = Table(title="Disk Inventory")
    table.add_column("Device", style="cyan")
    table.add_column("Model", style="white")
    table.add_column("Size", style="green")
    table.add_column("Type", style="yellow")
    table.add_column("Style", style="magenta")
    table.add_column("System", style="red")

    for disk in inventory.disks:
        table.add_row(
            disk.device_path,
            disk.model[:30] if disk.model else "Unknown",
            humanize.naturalsize(disk.size_bytes, binary=True),
            disk.disk_type.name,
            disk.partition_style.name,
            "Yes" if disk.is_system_disk else "",
        )

    console.print(table)
    console.print()

    # Display partitions
    for disk in inventory.disks:
        if disk.partitions:
            part_table = Table(title=f"Partitions on {disk.device_path}")
            part_table.add_column("#", style="dim")
            part_table.add_column("Device", style="cyan")
            part_table.add_column("Size", style="green")
            part_table.add_column("FS", style="yellow")
            part_table.add_column("Label", style="white")
            part_table.add_column("Mount", style="blue")
            part_table.add_column("Flags", style="magenta")

            for part in disk.partitions:
                flags = ", ".join(f.name for f in part.flags) if part.flags else ""
                part_table.add_row(
                    str(part.number),
                    part.device_path,
                    humanize.naturalsize(part.size_bytes, binary=True),
                    part.filesystem.value,
                    part.label or "",
                    part.mountpoint or "",
                    flags[:20],
                )

            console.print(part_table)
            console.print()


@cli.command("info")
@click.argument("device")
@click.pass_context
def disk_info(ctx: click.Context, device: str) -> None:
    """Show detailed information about a disk or partition."""
    session = get_session(ctx)
    json_output = ctx.obj.get("json_output", False)

    disk = session.platform.get_disk_info(device)
    if disk is None:
        # Try as partition
        partition = session.platform.get_partition_info(device)
        if partition is None:
            console.print(f"[red]Device not found: {device}[/red]")
            sys.exit(1)

        if json_output:
            import json

            click.echo(json.dumps(partition.to_dict(), indent=2, default=str))
        else:
            panel = Panel(
                f"""[cyan]Device:[/cyan] {partition.device_path}
[cyan]Number:[/cyan] {partition.number}
[cyan]Size:[/cyan] {humanize.naturalsize(partition.size_bytes, binary=True)}
[cyan]Filesystem:[/cyan] {partition.filesystem.value}
[cyan]Label:[/cyan] {partition.label or "(none)"}
[cyan]UUID:[/cyan] {partition.uuid or "(none)"}
[cyan]Mountpoint:[/cyan] {partition.mountpoint or "(not mounted)"}
[cyan]Flags:[/cyan] {', '.join(f.name for f in partition.flags) or "(none)"}""",
                title="Partition Information",
            )
            console.print(panel)
        return

    if json_output:
        import json

        click.echo(json.dumps(disk.to_dict(), indent=2, default=str))
    else:
        panel = Panel(
            f"""[cyan]Device:[/cyan] {disk.device_path}
[cyan]Model:[/cyan] {disk.model}
[cyan]Serial:[/cyan] {disk.serial or "(unknown)"}
[cyan]Vendor:[/cyan] {disk.vendor or "(unknown)"}
[cyan]Size:[/cyan] {humanize.naturalsize(disk.size_bytes, binary=True)}
[cyan]Sector Size:[/cyan] {disk.sector_size} bytes
[cyan]Type:[/cyan] {disk.disk_type.name}
[cyan]Partition Style:[/cyan] {disk.partition_style.name}
[cyan]Interface:[/cyan] {disk.interface or "(unknown)"}
[cyan]System Disk:[/cyan] {"Yes" if disk.is_system_disk else "No"}
[cyan]Removable:[/cyan] {"Yes" if disk.is_removable else "No"}
[cyan]Partitions:[/cyan] {len(disk.partitions)}
[cyan]Unallocated:[/cyan] {humanize.naturalsize(disk.unallocated_bytes, binary=True)}""",
            title="Disk Information",
        )
        console.print(panel)


@cli.command("create-partition")
@click.argument("disk")
@click.option("--size", "-s", help="Partition size (e.g., 10G, 500M)")
@click.option(
    "--filesystem",
    "-f",
    type=click.Choice(["ext4", "ext3", "xfs", "btrfs", "ntfs", "fat32", "exfat"]),
    default="ext4",
    help="Filesystem type",
)
@click.option("--label", "-l", help="Partition label")
@click.option("--dry-run", is_flag=True, help="Show what would be done")
@click.pass_context
def create_partition(
    ctx: click.Context,
    disk: str,
    size: str | None,
    filesystem: str,
    label: str | None,
    dry_run: bool,
) -> None:
    """Create a new partition on a disk."""
    session = get_session(ctx)

    # Check danger mode
    if session.danger_mode == DangerMode.DISABLED:
        console.print("[red]Error: Danger mode required for this operation[/red]")
        console.print("Run with --danger-mode flag and confirm to enable")
        sys.exit(1)

    # Parse size
    size_bytes = None
    if size:
        size_bytes = parse_size(size)
        if size_bytes is None:
            console.print(f"[red]Invalid size format: {size}[/red]")
            sys.exit(1)

    fs_map = {
        "ext4": FileSystem.EXT4,
        "ext3": FileSystem.EXT3,
        "xfs": FileSystem.XFS,
        "btrfs": FileSystem.BTRFS,
        "ntfs": FileSystem.NTFS,
        "fat32": FileSystem.FAT32,
        "exfat": FileSystem.EXFAT,
    }
    fs = fs_map[filesystem]

    from diskforge.core.models import PartitionCreateOptions

    options = PartitionCreateOptions(
        disk_path=disk,
        size_bytes=size_bytes,
        filesystem=fs,
        label=label,
    )

    if dry_run:
        console.print(Panel(f"""[yellow]DRY RUN - No changes will be made[/yellow]

Disk: {disk}
Size: {humanize.naturalsize(size_bytes, binary=True) if size_bytes else "All available"}
Filesystem: {filesystem}
Label: {label or "(none)"}""", title="Create Partition Plan"))
        return

    # Require confirmation
    confirm_str = session.safety.generate_confirmation_string(disk)
    console.print(f"[red]⚠️  This will modify the partition table on {disk}[/red]")
    user_confirm = click.prompt(f"Type '{confirm_str}' to confirm")

    if user_confirm != confirm_str:
        console.print("[red]Confirmation failed - operation cancelled[/red]")
        sys.exit(1)

    with console.status("Creating partition..."):
        success, message = session.platform.create_partition(options, dry_run=False)

    if success:
        console.print(f"[green]✓ {message}[/green]")
    else:
        console.print(f"[red]✗ {message}[/red]")
        sys.exit(1)


@cli.command("delete-partition")
@click.argument("partition")
@click.option("--dry-run", is_flag=True, help="Show what would be done")
@click.pass_context
def delete_partition(ctx: click.Context, partition: str, dry_run: bool) -> None:
    """Delete a partition."""
    session = get_session(ctx)

    if session.danger_mode == DangerMode.DISABLED:
        console.print("[red]Error: Danger mode required for this operation[/red]")
        sys.exit(1)

    if dry_run:
        console.print(Panel(f"[yellow]DRY RUN[/yellow]\n\nWould delete: {partition}", title="Delete Partition Plan"))
        return

    confirm_str = session.safety.generate_confirmation_string(partition)
    console.print(f"[red]⚠️  This will PERMANENTLY DELETE {partition}[/red]")
    user_confirm = click.prompt(f"Type '{confirm_str}' to confirm")

    if user_confirm != confirm_str:
        console.print("[red]Confirmation failed[/red]")
        sys.exit(1)

    with console.status("Deleting partition..."):
        success, message = session.platform.delete_partition(partition)

    if success:
        console.print(f"[green]✓ {message}[/green]")
    else:
        console.print(f"[red]✗ {message}[/red]")
        sys.exit(1)


@cli.command("format")
@click.argument("partition")
@click.option(
    "--filesystem",
    "-f",
    type=click.Choice(["ext4", "ext3", "xfs", "btrfs", "ntfs", "fat32", "exfat"]),
    required=True,
    help="Filesystem type",
)
@click.option("--label", "-l", help="Volume label")
@click.option("--quick/--full", default=True, help="Quick or full format")
@click.option("--dry-run", is_flag=True, help="Show what would be done")
@click.pass_context
def format_partition(
    ctx: click.Context,
    partition: str,
    filesystem: str,
    label: str | None,
    quick: bool,
    dry_run: bool,
) -> None:
    """Format a partition with a filesystem."""
    session = get_session(ctx)

    if session.danger_mode == DangerMode.DISABLED:
        console.print("[red]Error: Danger mode required[/red]")
        sys.exit(1)

    fs_map = {
        "ext4": FileSystem.EXT4,
        "ext3": FileSystem.EXT3,
        "xfs": FileSystem.XFS,
        "btrfs": FileSystem.BTRFS,
        "ntfs": FileSystem.NTFS,
        "fat32": FileSystem.FAT32,
        "exfat": FileSystem.EXFAT,
    }

    from diskforge.core.models import FormatOptions

    options = FormatOptions(
        partition_path=partition,
        filesystem=fs_map[filesystem],
        label=label,
        quick=quick,
    )

    if dry_run:
        console.print(Panel(f"""[yellow]DRY RUN[/yellow]

Partition: {partition}
Filesystem: {filesystem}
Label: {label or "(none)"}
Mode: {"Quick" if quick else "Full"}""", title="Format Plan"))
        return

    confirm_str = session.safety.generate_confirmation_string(partition)
    console.print(f"[red]⚠️  This will ERASE ALL DATA on {partition}[/red]")
    user_confirm = click.prompt(f"Type '{confirm_str}' to confirm")

    if user_confirm != confirm_str:
        console.print("[red]Confirmation failed[/red]")
        sys.exit(1)

    with console.status(f"Formatting {partition}..."):
        success, message = session.platform.format_partition(options)

    if success:
        console.print(f"[green]✓ {message}[/green]")
    else:
        console.print(f"[red]✗ {message}[/red]")
        sys.exit(1)


@cli.command("clone")
@click.argument("source")
@click.argument("target")
@click.option("--no-verify", is_flag=True, help="Skip verification")
@click.option("--dry-run", is_flag=True, help="Show what would be done")
@click.pass_context
def clone(
    ctx: click.Context,
    source: str,
    target: str,
    no_verify: bool,
    dry_run: bool,
) -> None:
    """Clone a disk or partition."""
    session = get_session(ctx)

    if session.danger_mode == DangerMode.DISABLED:
        console.print("[red]Error: Danger mode required[/red]")
        sys.exit(1)

    # Determine if disk or partition
    source_disk = session.platform.get_disk_info(source)
    is_disk = source_disk is not None

    if dry_run:
        console.print(Panel(f"""[yellow]DRY RUN[/yellow]

Source: {source} ({"disk" if is_disk else "partition"})
Target: {target}
Verify: {"No" if no_verify else "Yes"}""", title="Clone Plan"))
        return

    confirm_str = session.safety.generate_confirmation_string(target)
    console.print(f"[red]⚠️  This will DESTROY ALL DATA on {target}[/red]")
    user_confirm = click.prompt(f"Type '{confirm_str}' to confirm")

    if user_confirm != confirm_str:
        console.print("[red]Confirmation failed[/red]")
        sys.exit(1)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        console=console,
    ) as progress:
        task = progress.add_task("Cloning...", total=100)

        def update_progress(prog: Any) -> None:
            progress.update(task, completed=prog.percentage, description=prog.message)

        if is_disk:
            success, message = session.platform.clone_disk(
                source, target, verify=not no_verify
            )
        else:
            success, message = session.platform.clone_partition(
                source, target, verify=not no_verify
            )

    if success:
        console.print(f"[green]✓ {message}[/green]")
    else:
        console.print(f"[red]✗ {message}[/red]")
        sys.exit(1)


@cli.command("backup")
@click.argument("source")
@click.argument("output", type=click.Path(path_type=Path))
@click.option(
    "--compression",
    "-c",
    type=click.Choice(["none", "gzip", "lz4", "zstd"]),
    default="zstd",
    help="Compression algorithm",
)
@click.option("--no-verify", is_flag=True, help="Skip verification")
@click.option("--dry-run", is_flag=True, help="Show what would be done")
@click.pass_context
def backup(
    ctx: click.Context,
    source: str,
    output: Path,
    compression: str,
    no_verify: bool,
    dry_run: bool,
) -> None:
    """Create an image backup of a disk or partition."""
    session = get_session(ctx)

    compress = None if compression == "none" else compression

    if dry_run:
        console.print(Panel(f"""[yellow]DRY RUN[/yellow]

Source: {source}
Output: {output}
Compression: {compression}
Verify: {"No" if no_verify else "Yes"}""", title="Backup Plan"))
        return

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        console=console,
    ) as progress:
        task = progress.add_task("Creating backup...", total=100)

        success, message, info = session.platform.create_image(
            source, output, compression=compress, verify=not no_verify
        )

    if success:
        console.print(f"[green]✓ {message}[/green]")
        if info:
            console.print(f"Image size: {humanize.naturalsize(info.image_size_bytes, binary=True)}")
    else:
        console.print(f"[red]✗ {message}[/red]")
        sys.exit(1)


@cli.command("restore")
@click.argument("image", type=click.Path(exists=True, path_type=Path))
@click.argument("target")
@click.option("--no-verify", is_flag=True, help="Skip verification")
@click.option("--dry-run", is_flag=True, help="Show what would be done")
@click.pass_context
def restore(
    ctx: click.Context,
    image: Path,
    target: str,
    no_verify: bool,
    dry_run: bool,
) -> None:
    """Restore an image to a disk or partition."""
    session = get_session(ctx)

    if session.danger_mode == DangerMode.DISABLED:
        console.print("[red]Error: Danger mode required[/red]")
        sys.exit(1)

    if dry_run:
        console.print(Panel(f"""[yellow]DRY RUN[/yellow]

Image: {image}
Target: {target}
Verify: {"No" if no_verify else "Yes"}""", title="Restore Plan"))
        return

    confirm_str = session.safety.generate_confirmation_string(target)
    console.print(f"[red]⚠️  This will DESTROY ALL DATA on {target}[/red]")
    user_confirm = click.prompt(f"Type '{confirm_str}' to confirm")

    if user_confirm != confirm_str:
        console.print("[red]Confirmation failed[/red]")
        sys.exit(1)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        console=console,
    ) as progress:
        task = progress.add_task("Restoring...", total=100)

        success, message = session.platform.restore_image(
            image, target, verify=not no_verify
        )

    if success:
        console.print(f"[green]✓ {message}[/green]")
    else:
        console.print(f"[red]✗ {message}[/red]")
        sys.exit(1)


@cli.command("rescue")
@click.argument("output", type=click.Path(path_type=Path))
@click.option("--dry-run", is_flag=True, help="Show what would be done")
@click.pass_context
def rescue(ctx: click.Context, output: Path, dry_run: bool) -> None:
    """Create bootable rescue media."""
    session = get_session(ctx)

    if dry_run:
        console.print(Panel(f"[yellow]DRY RUN[/yellow]\n\nOutput: {output}", title="Rescue Media Plan"))
        return

    with console.status("Creating rescue media..."):
        success, message, artifacts = session.platform.create_rescue_media(output)

    if success:
        console.print(f"[green]✓ {message}[/green]")
        if artifacts:
            console.print("\nCreated files:")
            for key, path in artifacts.items():
                console.print(f"  {key}: {path}")
    else:
        console.print(f"[red]✗ {message}[/red]")
        sys.exit(1)


@cli.command("status")
@click.pass_context
def status(ctx: click.Context) -> None:
    """Show current session status."""
    session = get_session(ctx)

    panel = Panel(
        f"""[cyan]Session ID:[/cyan] {session.id[:8]}
[cyan]Danger Mode:[/cyan] {session.danger_mode.name}
[cyan]Platform:[/cyan] {session.platform.name}
[cyan]Admin:[/cyan] {"Yes" if session.platform.is_admin() else "No"}
[cyan]Started:[/cyan] {session.started_at.isoformat()}""",
        title="DiskForge Status",
    )
    console.print(panel)


def parse_size(size_str: str) -> int | None:
    """Parse size string like '10G' to bytes."""
    import re

    match = re.match(r"^(\d+(?:\.\d+)?)\s*([KMGT]?)B?$", size_str.upper())
    if not match:
        return None

    value = float(match.group(1))
    unit = match.group(2)

    multipliers = {
        "": 1,
        "K": 1024,
        "M": 1024**2,
        "G": 1024**3,
        "T": 1024**4,
    }

    return int(value * multipliers.get(unit, 1))


def main() -> None:
    """Main entry point."""
    try:
        cli(obj={})
    except KeyboardInterrupt:
        console.print("\n[yellow]Operation cancelled[/yellow]")
        sys.exit(130)
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)


if __name__ == "__main__":
    main()
