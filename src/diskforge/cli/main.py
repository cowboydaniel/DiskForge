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
from diskforge.core.models import (
    DuplicateRemovalOptions,
    DuplicateScanOptions,
    FileRemovalOptions,
    FileSystem,
    FreeSpaceOptions,
    JunkCleanupOptions,
    LargeFileScanOptions,
    MoveApplicationOptions,
    BadSectorScanOptions,
    SurfaceTestOptions,
    DiskSpeedTestOptions,
)
from diskforge.core.safety import DangerMode
from diskforge.core.session import Session

console = Console()


def get_session(ctx: click.Context) -> Session:
    """Get or create session from context."""
    if "session" not in ctx.obj:
        config = ctx.obj.get("config") or load_config()
        ctx.obj["session"] = Session(config=config)
    return ctx.obj["session"]


def require_platform(session: Session, platform_name: str, feature: str) -> None:
    """Ensure the current platform matches the required platform."""
    if session.platform.name != platform_name:
        console.print(f"[red]{feature} is only available on {platform_name}.[/red]")
        sys.exit(1)


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


@cli.command("health")
@click.argument("device")
@click.pass_context
def disk_health(ctx: click.Context, device: str) -> None:
    """Run a disk health (SMART) check."""
    session = get_session(ctx)
    json_output = ctx.obj.get("json_output", False)

    result = session.platform.disk_health_check(device)

    if json_output:
        import json

        click.echo(json.dumps(result.to_dict(), indent=2, default=str))
        return

    status_color = "green" if result.healthy else "red"
    smart_state = "Available" if result.smart_available else "Unavailable"
    panel = Panel(
        f"""[cyan]Device:[/cyan] {result.device_path}
[cyan]SMART:[/cyan] {smart_state}
[cyan]Status:[/cyan] [{status_color}]{result.status}[/{status_color}]
[cyan]Message:[/cyan] {result.message}
[cyan]Temperature:[/cyan] {result.temperature_c if result.temperature_c is not None else "N/A"}""",
        title="Disk Health Check",
    )
    console.print(panel)

    if not result.smart_available:
        sys.exit(1)


@cli.command("speed-test")
@click.argument("device")
@click.option("--size-mib", type=int, default=256, help="Sample size in MiB")
@click.option("--block-mib", type=int, default=4, help="Block size in MiB")
@click.pass_context
def speed_test(ctx: click.Context, device: str, size_mib: int, block_mib: int) -> None:
    """Run a disk read speed test."""
    session = get_session(ctx)
    json_output = ctx.obj.get("json_output", False)

    options = DiskSpeedTestOptions(
        device_path=device,
        sample_size_bytes=max(size_mib, 1) * 1024 * 1024,
        block_size_bytes=max(block_mib, 1) * 1024 * 1024,
    )
    result = session.platform.disk_speed_test(options)

    if json_output:
        import json

        click.echo(json.dumps(result.to_dict(), indent=2, default=str))
        return

    if result.success:
        rate = humanize.naturalsize(result.read_bytes_per_sec, binary=True)
        duration = f"{result.duration_seconds:.2f}s"
        console.print(
            Panel(
                f"""[cyan]Device:[/cyan] {result.device_path}
[cyan]Sample size:[/cyan] {humanize.naturalsize(result.sample_size_bytes, binary=True)}
[cyan]Block size:[/cyan] {humanize.naturalsize(result.block_size_bytes, binary=True)}
[cyan]Read rate:[/cyan] {rate}/s
[cyan]Duration:[/cyan] {duration}""",
                title="Disk Speed Test",
            )
        )
    else:
        console.print(f"[red]✗ {result.message}[/red]")
        sys.exit(1)


@cli.command("bad-sectors")
@click.argument("device")
@click.option("--block-size", type=int, default=4096, help="Block size in bytes")
@click.option("--passes", type=int, default=1, help="Number of passes")
@click.pass_context
def bad_sectors(ctx: click.Context, device: str, block_size: int, passes: int) -> None:
    """Scan disk for bad sectors."""
    session = get_session(ctx)
    json_output = ctx.obj.get("json_output", False)

    options = BadSectorScanOptions(
        device_path=device,
        block_size=max(block_size, 512),
        passes=max(passes, 1),
    )
    result = session.platform.bad_sector_scan(options)

    if json_output:
        import json

        click.echo(json.dumps(result.to_dict(), indent=2, default=str))
        return

    if result.success:
        bad_list = ", ".join(str(b) for b in result.bad_sectors[:10])
        summary = f"{result.bad_sector_count} bad sectors detected"
        if result.bad_sector_count > 10:
            summary += " (showing first 10)"
        console.print(
            Panel(
                f"""[cyan]Device:[/cyan] {result.device_path}
[cyan]Block size:[/cyan] {result.block_size} bytes
[cyan]Passes:[/cyan] {result.passes}
[cyan]Duration:[/cyan] {result.duration_seconds:.1f}s
[cyan]Summary:[/cyan] {summary}
[cyan]Bad sectors:[/cyan] {bad_list if bad_list else "None"}""",
                title="Bad Sector Scan",
            )
        )
    else:
        console.print(f"[red]✗ {result.message}[/red]")
        sys.exit(1)


@cli.command("surface-test")
@click.argument("device")
@click.option(
    "--mode",
    type=click.Choice(["read", "non-destructive", "destructive"]),
    default="read",
    help="Surface test mode",
)
@click.option("--block-size", type=int, default=4096, help="Block size in bytes")
@click.option("--passes", type=int, default=1, help="Number of passes")
@click.pass_context
def surface_test(
    ctx: click.Context,
    device: str,
    mode: str,
    block_size: int,
    passes: int,
) -> None:
    """Run a disk surface test."""
    session = get_session(ctx)
    json_output = ctx.obj.get("json_output", False)

    options = SurfaceTestOptions(
        device_path=device,
        mode=mode,
        block_size=max(block_size, 512),
        passes=max(passes, 1),
    )
    result = session.platform.surface_test(options)

    if json_output:
        import json

        click.echo(json.dumps(result.to_dict(), indent=2, default=str))
        return

    if result.success:
        bad_list = ", ".join(str(b) for b in result.bad_sectors[:10])
        summary = f"{result.bad_sector_count} bad sectors detected"
        if result.bad_sector_count > 10:
            summary += " (showing first 10)"
        console.print(
            Panel(
                f"""[cyan]Device:[/cyan] {result.device_path}
[cyan]Mode:[/cyan] {result.mode}
[cyan]Block size:[/cyan] {result.block_size} bytes
[cyan]Passes:[/cyan] {result.passes}
[cyan]Duration:[/cyan] {result.duration_seconds:.1f}s
[cyan]Summary:[/cyan] {summary}
[cyan]Bad sectors:[/cyan] {bad_list if bad_list else "None"}""",
                title="Surface Test",
            )
        )
    else:
        console.print(f"[red]✗ {result.message}[/red]")
        sys.exit(1)


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


@cli.command("resize-move")
@click.argument("partition")
@click.option("--size", "-s", required=True, help="New partition size (e.g., 10G, 500M)")
@click.option("--start-sector", type=int, help="New start sector")
@click.option("--align-mb", type=int, default=1, show_default=True, help="Alignment in MB")
@click.option("--dry-run", is_flag=True, help="Show what would be done")
@click.pass_context
def resize_move_partition(
    ctx: click.Context,
    partition: str,
    size: str,
    start_sector: int | None,
    align_mb: int,
    dry_run: bool,
) -> None:
    """Resize or move a partition."""
    session = get_session(ctx)

    if session.danger_mode == DangerMode.DISABLED:
        console.print("[red]Error: Danger mode required for this operation[/red]")
        sys.exit(1)

    size_bytes = parse_size(size)
    if size_bytes is None:
        console.print(f"[red]Invalid size format: {size}[/red]")
        sys.exit(1)

    from diskforge.core.models import ResizeMoveOptions

    options = ResizeMoveOptions(
        partition_path=partition,
        new_size_bytes=size_bytes,
        new_start_sector=start_sector,
        align_to_mb=align_mb,
    )

    if dry_run:
        console.print(Panel(f"""[yellow]DRY RUN[/yellow]

Partition: {partition}
New size: {humanize.naturalsize(size_bytes, binary=True)}
Start sector: {start_sector or "(unchanged)"}
Align: {align_mb} MB""", title="Resize/Move Partition Plan"))
        return

    confirm_str = session.safety.generate_confirmation_string(partition)
    console.print(f"[red]⚠️  This will resize/move {partition}[/red]")
    user_confirm = click.prompt(f"Type '{confirm_str}' to confirm")

    if user_confirm != confirm_str:
        console.print("[red]Confirmation failed[/red]")
        sys.exit(1)

    with console.status("Resizing/moving partition..."):
        success, message = session.platform.resize_move_partition(options)

    if success:
        console.print(f"[green]✓ {message}[/green]")
    else:
        console.print(f"[red]✗ {message}[/red]")
        sys.exit(1)


@cli.command("merge-partitions")
@click.argument("primary_partition")
@click.argument("secondary_partition")
@click.option("--dry-run", is_flag=True, help="Show what would be done")
@click.pass_context
def merge_partitions(
    ctx: click.Context,
    primary_partition: str,
    secondary_partition: str,
    dry_run: bool,
) -> None:
    """Merge two partitions."""
    session = get_session(ctx)

    if session.danger_mode == DangerMode.DISABLED:
        console.print("[red]Error: Danger mode required for this operation[/red]")
        sys.exit(1)

    from diskforge.core.models import MergePartitionsOptions

    options = MergePartitionsOptions(
        primary_partition_path=primary_partition,
        secondary_partition_path=secondary_partition,
    )

    if dry_run:
        console.print(Panel(f"""[yellow]DRY RUN[/yellow]

Primary: {primary_partition}
Secondary: {secondary_partition}""", title="Merge Partitions Plan"))
        return

    confirm_str = session.safety.generate_confirmation_string(primary_partition)
    console.print(f"[red]⚠️  This will merge {secondary_partition} into {primary_partition}[/red]")
    user_confirm = click.prompt(f"Type '{confirm_str}' to confirm")

    if user_confirm != confirm_str:
        console.print("[red]Confirmation failed[/red]")
        sys.exit(1)

    with console.status("Merging partitions..."):
        success, message = session.platform.merge_partitions(options)

    if success:
        console.print(f"[green]✓ {message}[/green]")
    else:
        console.print(f"[red]✗ {message}[/red]")
        sys.exit(1)


@cli.command("split-partition")
@click.argument("partition")
@click.option("--size", "-s", required=True, help="Size of new partition (e.g., 10G, 500M)")
@click.option(
    "--filesystem",
    "-f",
    type=click.Choice(["ext4", "ext3", "xfs", "btrfs", "ntfs", "fat32", "exfat"]),
    help="Filesystem type for the new partition",
)
@click.option("--label", "-l", help="Label for the new partition")
@click.option("--align-mb", type=int, default=1, show_default=True, help="Alignment in MB")
@click.option("--dry-run", is_flag=True, help="Show what would be done")
@click.pass_context
def split_partition(
    ctx: click.Context,
    partition: str,
    size: str,
    filesystem: str | None,
    label: str | None,
    align_mb: int,
    dry_run: bool,
) -> None:
    """Split a partition into two."""
    session = get_session(ctx)

    if session.danger_mode == DangerMode.DISABLED:
        console.print("[red]Error: Danger mode required for this operation[/red]")
        sys.exit(1)

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
    fs = fs_map.get(filesystem) if filesystem else None

    from diskforge.core.models import SplitPartitionOptions

    options = SplitPartitionOptions(
        partition_path=partition,
        split_size_bytes=size_bytes,
        filesystem=fs,
        label=label,
        align_to_mb=align_mb,
    )

    if dry_run:
        console.print(Panel(f"""[yellow]DRY RUN[/yellow]

Partition: {partition}
New size: {humanize.naturalsize(size_bytes, binary=True)}
Filesystem: {filesystem or "(unchanged)"}
Label: {label or "(none)"}
Align: {align_mb} MB""", title="Split Partition Plan"))
        return

    confirm_str = session.safety.generate_confirmation_string(partition)
    console.print(f"[red]⚠️  This will split {partition}[/red]")
    user_confirm = click.prompt(f"Type '{confirm_str}' to confirm")

    if user_confirm != confirm_str:
        console.print("[red]Confirmation failed[/red]")
        sys.exit(1)

    with console.status("Splitting partition..."):
        success, message = session.platform.split_partition(options)

    if success:
        console.print(f"[green]✓ {message}[/green]")
    else:
        console.print(f"[red]✗ {message}[/red]")
        sys.exit(1)


@cli.command("extend-partition")
@click.argument("partition")
@click.option("--size", "-s", required=True, help="New partition size (e.g., 10G, 500M)")
@click.option("--dry-run", is_flag=True, help="Show what would be done")
@click.pass_context
def extend_partition(
    ctx: click.Context,
    partition: str,
    size: str,
    dry_run: bool,
) -> None:
    """Extend a partition."""
    session = get_session(ctx)

    if session.danger_mode == DangerMode.DISABLED:
        console.print("[red]Error: Danger mode required[/red]")
        sys.exit(1)

    size_bytes = parse_size(size)
    if size_bytes is None:
        console.print(f"[red]Invalid size format: {size}[/red]")
        sys.exit(1)

    if dry_run:
        console.print(Panel(f"""[yellow]DRY RUN[/yellow]

Partition: {partition}
New size: {humanize.naturalsize(size_bytes, binary=True)}""", title="Extend Partition Plan"))
        return

    confirm_str = session.safety.generate_confirmation_string(partition)
    console.print(f"[red]⚠️  This will extend {partition}[/red]")
    user_confirm = click.prompt(f"Type '{confirm_str}' to confirm")

    if user_confirm != confirm_str:
        console.print("[red]Confirmation failed[/red]")
        sys.exit(1)

    with console.status("Extending partition..."):
        success, message = session.platform.extend_partition(partition, size_bytes)

    if success:
        console.print(f"[green]✓ {message}[/green]")
    else:
        console.print(f"[red]✗ {message}[/red]")
        sys.exit(1)


@cli.command("shrink-partition")
@click.argument("partition")
@click.option("--size", "-s", required=True, help="New partition size (e.g., 10G, 500M)")
@click.option("--dry-run", is_flag=True, help="Show what would be done")
@click.pass_context
def shrink_partition(
    ctx: click.Context,
    partition: str,
    size: str,
    dry_run: bool,
) -> None:
    """Shrink a partition."""
    session = get_session(ctx)

    if session.danger_mode == DangerMode.DISABLED:
        console.print("[red]Error: Danger mode required[/red]")
        sys.exit(1)

    size_bytes = parse_size(size)
    if size_bytes is None:
        console.print(f"[red]Invalid size format: {size}[/red]")
        sys.exit(1)

    if dry_run:
        console.print(Panel(f"""[yellow]DRY RUN[/yellow]

Partition: {partition}
New size: {humanize.naturalsize(size_bytes, binary=True)}""", title="Shrink Partition Plan"))
        return

    confirm_str = session.safety.generate_confirmation_string(partition)
    console.print(f"[red]⚠️  This will shrink {partition}[/red]")
    user_confirm = click.prompt(f"Type '{confirm_str}' to confirm")

    if user_confirm != confirm_str:
        console.print("[red]Confirmation failed[/red]")
        sys.exit(1)

    with console.status("Shrinking partition..."):
        success, message = session.platform.shrink_partition(partition, size_bytes)

    if success:
        console.print(f"[green]✓ {message}[/green]")
    else:
        console.print(f"[red]✗ {message}[/red]")
        sys.exit(1)


@cli.command("resize-move-dynamic-volume")
@click.argument("volume")
@click.option("--size", "-s", required=True, help="Target size for the dynamic volume (e.g., 10G, 500M)")
@click.option("--start-sector", type=int, help="Optional new start sector (platform-specific)")
@click.option("--dry-run", is_flag=True, help="Show what would be done")
@click.pass_context
def resize_move_dynamic_volume(
    ctx: click.Context,
    volume: str,
    size: str,
    start_sector: int | None,
    dry_run: bool,
) -> None:
    """Resize or move a dynamic volume."""
    session = get_session(ctx)

    if session.danger_mode == DangerMode.DISABLED:
        console.print("[red]Error: Danger mode required for this operation[/red]")
        sys.exit(1)

    size_bytes = parse_size(size)
    if size_bytes is None:
        console.print(f"[red]Invalid size format: {size}[/red]")
        sys.exit(1)

    from diskforge.core.models import DynamicVolumeResizeMoveOptions

    options = DynamicVolumeResizeMoveOptions(
        volume_id=volume,
        new_size_bytes=size_bytes,
        new_start_sector=start_sector,
    )

    if dry_run:
        console.print(Panel(f"""[yellow]DRY RUN[/yellow]

Dynamic volume: {volume}
New size: {humanize.naturalsize(size_bytes, binary=True)}
Start sector: {start_sector or "(unchanged)"}""", title="Resize/Move Dynamic Volume Plan"))
        return

    confirm_str = session.safety.generate_confirmation_string(volume)
    console.print(f"[red]⚠️  This will resize/move dynamic volume {volume}[/red]")
    user_confirm = click.prompt(f"Type '{confirm_str}' to confirm")

    if user_confirm != confirm_str:
        console.print("[red]Confirmation failed[/red]")
        sys.exit(1)

    with console.status("Resizing/moving dynamic volume..."):
        success, message = session.platform.resize_move_dynamic_volume(options)

    if success:
        console.print(f"[green]✓ {message}[/green]")
    else:
        console.print(f"[red]✗ {message}[/red]")
        sys.exit(1)


@cli.command("extend-dynamic-volume")
@click.argument("volume")
@click.option("--size", "-s", required=True, help="Target size for the dynamic volume (e.g., 10G, 500M)")
@click.option("--dry-run", is_flag=True, help="Show what would be done")
@click.pass_context
def extend_dynamic_volume(
    ctx: click.Context,
    volume: str,
    size: str,
    dry_run: bool,
) -> None:
    """Extend a dynamic volume."""
    session = get_session(ctx)

    if session.danger_mode == DangerMode.DISABLED:
        console.print("[red]Error: Danger mode required[/red]")
        sys.exit(1)

    size_bytes = parse_size(size)
    if size_bytes is None:
        console.print(f"[red]Invalid size format: {size}[/red]")
        sys.exit(1)

    if dry_run:
        console.print(Panel(f"""[yellow]DRY RUN[/yellow]

Dynamic volume: {volume}
New size: {humanize.naturalsize(size_bytes, binary=True)}""", title="Extend Dynamic Volume Plan"))
        return

    confirm_str = session.safety.generate_confirmation_string(volume)
    console.print(f"[red]⚠️  This will extend dynamic volume {volume}[/red]")
    user_confirm = click.prompt(f"Type '{confirm_str}' to confirm")

    if user_confirm != confirm_str:
        console.print("[red]Confirmation failed[/red]")
        sys.exit(1)

    with console.status("Extending dynamic volume..."):
        success, message = session.platform.extend_dynamic_volume(volume, size_bytes)

    if success:
        console.print(f"[green]✓ {message}[/green]")
    else:
        console.print(f"[red]✗ {message}[/red]")
        sys.exit(1)


@cli.command("shrink-dynamic-volume")
@click.argument("volume")
@click.option("--size", "-s", required=True, help="Target size for the dynamic volume (e.g., 10G, 500M)")
@click.option("--dry-run", is_flag=True, help="Show what would be done")
@click.pass_context
def shrink_dynamic_volume(
    ctx: click.Context,
    volume: str,
    size: str,
    dry_run: bool,
) -> None:
    """Shrink a dynamic volume."""
    session = get_session(ctx)

    if session.danger_mode == DangerMode.DISABLED:
        console.print("[red]Error: Danger mode required[/red]")
        sys.exit(1)

    size_bytes = parse_size(size)
    if size_bytes is None:
        console.print(f"[red]Invalid size format: {size}[/red]")
        sys.exit(1)

    if dry_run:
        console.print(Panel(f"""[yellow]DRY RUN[/yellow]

Dynamic volume: {volume}
New size: {humanize.naturalsize(size_bytes, binary=True)}""", title="Shrink Dynamic Volume Plan"))
        return

    confirm_str = session.safety.generate_confirmation_string(volume)
    console.print(f"[red]⚠️  This will shrink dynamic volume {volume}[/red]")
    user_confirm = click.prompt(f"Type '{confirm_str}' to confirm")

    if user_confirm != confirm_str:
        console.print("[red]Confirmation failed[/red]")
        sys.exit(1)

    with console.status("Shrinking dynamic volume..."):
        success, message = session.platform.shrink_dynamic_volume(volume, size_bytes)

    if success:
        console.print(f"[green]✓ {message}[/green]")
    else:
        console.print(f"[red]✗ {message}[/red]")
        sys.exit(1)


@cli.command("allocate-free-space")
@click.argument("disk")
@click.argument("source_partition")
@click.argument("target_partition")
@click.option("--size", "-s", help="Space to allocate (e.g., 10G, 500M)")
@click.option("--dry-run", is_flag=True, help="Show what would be done")
@click.pass_context
def allocate_free_space(
    ctx: click.Context,
    disk: str,
    source_partition: str,
    target_partition: str,
    size: str | None,
    dry_run: bool,
) -> None:
    """Allocate free space between partitions."""
    session = get_session(ctx)

    if session.danger_mode == DangerMode.DISABLED:
        console.print("[red]Error: Danger mode required[/red]")
        sys.exit(1)

    from diskforge.core.models import AllocateFreeSpaceOptions

    size_bytes = parse_size(size) if size else None
    if size and size_bytes is None:
        console.print(f"[red]Invalid size format: {size}[/red]")
        sys.exit(1)

    options = AllocateFreeSpaceOptions(
        disk_path=disk,
        source_partition_path=source_partition,
        target_partition_path=target_partition,
        size_bytes=size_bytes,
    )

    if dry_run:
        console.print(Panel(f"""[yellow]DRY RUN[/yellow]

Disk: {disk}
From: {source_partition}
To: {target_partition}
Size: {humanize.naturalsize(size_bytes, binary=True) if size_bytes else "All available"}""", title="Allocate Free Space Plan"))
        return

    confirm_str = session.safety.generate_confirmation_string(disk)
    console.print(f"[red]⚠️  This will reallocate space on {disk}[/red]")
    user_confirm = click.prompt(f"Type '{confirm_str}' to confirm")

    if user_confirm != confirm_str:
        console.print("[red]Confirmation failed[/red]")
        sys.exit(1)

    with console.status("Allocating free space..."):
        success, message = session.platform.allocate_free_space(options)

    if success:
        console.print(f"[green]✓ {message}[/green]")
    else:
        console.print(f"[red]✗ {message}[/red]")
        sys.exit(1)


@cli.command("one-click-adjust")
@click.argument("disk")
@click.option("--target-partition", help="Target partition device path")
@click.option(
    "--prioritize-system/--no-prioritize-system",
    default=True,
    help="Prioritize system partition during adjustment",
)
@click.option("--dry-run", is_flag=True, help="Show what would be done")
@click.pass_context
def one_click_adjust(
    ctx: click.Context,
    disk: str,
    target_partition: str | None,
    prioritize_system: bool,
    dry_run: bool,
) -> None:
    """Run one-click space adjustment."""
    session = get_session(ctx)

    if session.danger_mode == DangerMode.DISABLED:
        console.print("[red]Error: Danger mode required[/red]")
        sys.exit(1)

    from diskforge.core.models import OneClickAdjustOptions

    options = OneClickAdjustOptions(
        disk_path=disk,
        target_partition_path=target_partition,
        prioritize_system=prioritize_system,
    )

    if dry_run:
        console.print(Panel(f"""[yellow]DRY RUN[/yellow]

Disk: {disk}
Target: {target_partition or "Auto-select"}
Prioritize system: {"Yes" if prioritize_system else "No"}""", title="One-Click Adjust Plan"))
        return

    confirm_str = session.safety.generate_confirmation_string(disk)
    console.print(f"[red]⚠️  This will auto-adjust space on {disk}[/red]")
    user_confirm = click.prompt(f"Type '{confirm_str}' to confirm")

    if user_confirm != confirm_str:
        console.print("[red]Confirmation failed[/red]")
        sys.exit(1)

    with console.status("Adjusting space..."):
        success, message = session.platform.one_click_adjust_space(options)

    if success:
        console.print(f"[green]✓ {message}[/green]")
    else:
        console.print(f"[red]✗ {message}[/red]")
        sys.exit(1)


@cli.command("quick-partition")
@click.argument("disk")
@click.option("--count", type=int, default=2, show_default=True, help="Number of partitions")
@click.option(
    "--filesystem",
    "-f",
    type=click.Choice(["ext4", "ext3", "xfs", "btrfs", "ntfs", "fat32", "exfat"]),
    default="ext4",
    show_default=True,
    help="Filesystem type",
)
@click.option("--label-prefix", help="Partition label prefix")
@click.option("--size-per-partition", help="Size per partition (e.g., 10G, 500M)")
@click.option(
    "--use-entire-disk/--no-use-entire-disk",
    default=True,
    show_default=True,
    help="Use entire disk capacity",
)
@click.option("--dry-run", is_flag=True, help="Show what would be done")
@click.pass_context
def quick_partition(
    ctx: click.Context,
    disk: str,
    count: int,
    filesystem: str,
    label_prefix: str | None,
    size_per_partition: str | None,
    use_entire_disk: bool,
    dry_run: bool,
) -> None:
    """Quickly partition a disk."""
    session = get_session(ctx)

    if session.danger_mode == DangerMode.DISABLED:
        console.print("[red]Error: Danger mode required[/red]")
        sys.exit(1)

    from diskforge.core.models import QuickPartitionOptions

    size_bytes = parse_size(size_per_partition) if size_per_partition else None
    if size_per_partition and size_bytes is None:
        console.print(f"[red]Invalid size format: {size_per_partition}[/red]")
        sys.exit(1)

    if count <= 0:
        console.print("[red]Partition count must be greater than zero[/red]")
        sys.exit(1)

    if not use_entire_disk and size_bytes is None:
        console.print("[red]Size per partition is required when not using entire disk[/red]")
        sys.exit(1)

    options = QuickPartitionOptions(
        disk_path=disk,
        partition_count=count,
        filesystem=FileSystem(filesystem),
        label_prefix=label_prefix,
        partition_size_bytes=size_bytes,
        use_entire_disk=use_entire_disk,
    )

    if dry_run:
        console.print(Panel(f"""[yellow]DRY RUN[/yellow]

Disk: {disk}
Count: {count}
Filesystem: {filesystem}
Label prefix: {label_prefix or "(none)"}
Size per partition: {humanize.naturalsize(size_bytes, binary=True) if size_bytes else "Auto"}
Use entire disk: {"Yes" if use_entire_disk else "No"}""", title="Quick Partition Plan"))
        return

    confirm_str = session.safety.generate_confirmation_string(disk)
    console.print(f"[red]⚠️  This will partition {disk}[/red]")
    user_confirm = click.prompt(f"Type '{confirm_str}' to confirm")

    if user_confirm != confirm_str:
        console.print("[red]Confirmation failed[/red]")
        sys.exit(1)

    with console.status("Partitioning disk..."):
        success, message = session.platform.quick_partition_disk(options)

    if success:
        console.print(f"[green]✓ {message}[/green]")
    else:
        console.print(f"[red]✗ {message}[/red]")
        sys.exit(1)


@cli.command("set-drive-letter")
@click.argument("partition")
@click.argument("letter")
@click.option("--dry-run", is_flag=True, help="Show what would be done")
@click.pass_context
def set_drive_letter(ctx: click.Context, partition: str, letter: str, dry_run: bool) -> None:
    """Change a partition drive letter."""
    session = get_session(ctx)

    if session.danger_mode == DangerMode.DISABLED:
        console.print("[red]Error: Danger mode required[/red]")
        sys.exit(1)

    from diskforge.core.models import PartitionAttributeOptions

    letter = letter.strip().upper()
    if len(letter) != 1 or not letter.isalpha():
        console.print("[red]Drive letter must be a single alphabetic character[/red]")
        sys.exit(1)

    options = PartitionAttributeOptions(partition_path=partition, drive_letter=letter)

    if dry_run:
        console.print(Panel(f"""[yellow]DRY RUN[/yellow]

Partition: {partition}
Drive letter: {letter}""", title="Set Drive Letter Plan"))
        return

    confirm_str = session.safety.generate_confirmation_string(partition)
    console.print(f"[red]⚠️  This will change drive letter for {partition}[/red]")
    user_confirm = click.prompt(f"Type '{confirm_str}' to confirm")

    if user_confirm != confirm_str:
        console.print("[red]Confirmation failed[/red]")
        sys.exit(1)

    with console.status("Updating drive letter..."):
        success, message = session.platform.change_partition_attributes(options)

    if success:
        console.print(f"[green]✓ {message}[/green]")
    else:
        console.print(f"[red]✗ {message}[/red]")
        sys.exit(1)


@cli.command("set-partition-label")
@click.argument("partition")
@click.argument("label")
@click.option("--dry-run", is_flag=True, help="Show what would be done")
@click.pass_context
def set_partition_label(ctx: click.Context, partition: str, label: str, dry_run: bool) -> None:
    """Change a partition label."""
    session = get_session(ctx)

    if session.danger_mode == DangerMode.DISABLED:
        console.print("[red]Error: Danger mode required[/red]")
        sys.exit(1)

    from diskforge.core.models import PartitionAttributeOptions

    options = PartitionAttributeOptions(partition_path=partition, label=label)

    if dry_run:
        console.print(Panel(f"""[yellow]DRY RUN[/yellow]

Partition: {partition}
Label: {label}""", title="Set Partition Label Plan"))
        return

    confirm_str = session.safety.generate_confirmation_string(partition)
    console.print(f"[red]⚠️  This will change label for {partition}[/red]")
    user_confirm = click.prompt(f"Type '{confirm_str}' to confirm")

    if user_confirm != confirm_str:
        console.print("[red]Confirmation failed[/red]")
        sys.exit(1)

    with console.status("Updating label..."):
        success, message = session.platform.change_partition_attributes(options)

    if success:
        console.print(f"[green]✓ {message}[/green]")
    else:
        console.print(f"[red]✗ {message}[/red]")
        sys.exit(1)


@cli.command("set-partition-type")
@click.argument("partition")
@click.argument("type_id")
@click.option("--dry-run", is_flag=True, help="Show what would be done")
@click.pass_context
def set_partition_type(ctx: click.Context, partition: str, type_id: str, dry_run: bool) -> None:
    """Change a partition type ID."""
    session = get_session(ctx)

    if session.danger_mode == DangerMode.DISABLED:
        console.print("[red]Error: Danger mode required[/red]")
        sys.exit(1)

    from diskforge.core.models import PartitionAttributeOptions

    options = PartitionAttributeOptions(partition_path=partition, partition_type_id=type_id)

    if dry_run:
        console.print(Panel(f"""[yellow]DRY RUN[/yellow]

Partition: {partition}
Partition type ID: {type_id}""", title="Set Partition Type Plan"))
        return

    confirm_str = session.safety.generate_confirmation_string(partition)
    console.print(f"[red]⚠️  This will change partition type for {partition}[/red]")
    user_confirm = click.prompt(f"Type '{confirm_str}' to confirm")

    if user_confirm != confirm_str:
        console.print("[red]Confirmation failed[/red]")
        sys.exit(1)

    with console.status("Updating partition type..."):
        success, message = session.platform.change_partition_attributes(options)

    if success:
        console.print(f"[green]✓ {message}[/green]")
    else:
        console.print(f"[red]✗ {message}[/red]")
        sys.exit(1)


@cli.command("set-partition-serial")
@click.argument("partition")
@click.argument("serial")
@click.option("--dry-run", is_flag=True, help="Show what would be done")
@click.pass_context
def set_partition_serial(ctx: click.Context, partition: str, serial: str, dry_run: bool) -> None:
    """Change a partition serial number."""
    session = get_session(ctx)

    if session.danger_mode == DangerMode.DISABLED:
        console.print("[red]Error: Danger mode required[/red]")
        sys.exit(1)

    from diskforge.core.models import PartitionAttributeOptions

    options = PartitionAttributeOptions(partition_path=partition, serial_number=serial)

    if dry_run:
        console.print(Panel(f"""[yellow]DRY RUN[/yellow]

Partition: {partition}
Serial: {serial}""", title="Set Partition Serial Plan"))
        return

    confirm_str = session.safety.generate_confirmation_string(partition)
    console.print(f"[red]⚠️  This will change serial number for {partition}[/red]")
    user_confirm = click.prompt(f"Type '{confirm_str}' to confirm")

    if user_confirm != confirm_str:
        console.print("[red]Confirmation failed[/red]")
        sys.exit(1)

    with console.status("Updating serial number..."):
        success, message = session.platform.change_partition_attributes(options)

    if success:
        console.print(f"[green]✓ {message}[/green]")
    else:
        console.print(f"[red]✗ {message}[/red]")
        sys.exit(1)


@cli.command("initialize-disk")
@click.argument("disk")
@click.option(
    "--style",
    type=click.Choice(["gpt", "mbr"], case_sensitive=False),
    default="gpt",
    show_default=True,
    help="Partition style",
)
@click.option("--dry-run", is_flag=True, help="Show what would be done")
@click.pass_context
def initialize_disk(
    ctx: click.Context,
    disk: str,
    style: str,
    dry_run: bool,
) -> None:
    """Initialize a disk."""
    session = get_session(ctx)

    if session.danger_mode == DangerMode.DISABLED:
        console.print("[red]Error: Danger mode required[/red]")
        sys.exit(1)

    from diskforge.core.models import InitializeDiskOptions, PartitionStyle

    style_map = {"gpt": PartitionStyle.GPT, "mbr": PartitionStyle.MBR}
    options = InitializeDiskOptions(
        disk_path=disk,
        partition_style=style_map[style.lower()],
    )

    if dry_run:
        console.print(Panel(f"""[yellow]DRY RUN[/yellow]

Disk: {disk}
Style: {options.partition_style.name}""", title="Initialize Disk Plan"))
        return

    confirm_str = session.safety.generate_confirmation_string(disk)
    console.print(f"[red]⚠️  This will initialize {disk}[/red]")
    user_confirm = click.prompt(f"Type '{confirm_str}' to confirm")

    if user_confirm != confirm_str:
        console.print("[red]Confirmation failed[/red]")
        sys.exit(1)

    with console.status("Initializing disk..."):
        success, message = session.platform.initialize_disk(options)

    if success:
        console.print(f"[green]✓ {message}[/green]")
    else:
        console.print(f"[red]✗ {message}[/red]")
        sys.exit(1)


@cli.command("align-4k")
@click.argument("partition")
@click.option("--dry-run", is_flag=True, help="Show what would be done")
@click.pass_context
def align_4k(ctx: click.Context, partition: str, dry_run: bool) -> None:
    """Align a partition to 4K boundaries."""
    session = get_session(ctx)

    if session.danger_mode == DangerMode.DISABLED:
        console.print("[red]Error: Danger mode required[/red]")
        sys.exit(1)

    from diskforge.core.models import AlignOptions

    options = AlignOptions(partition_path=partition)

    if dry_run:
        console.print(Panel(f"""[yellow]DRY RUN[/yellow]

Partition: {partition}
Alignment: 4K""", title="Align 4K Plan"))
        return

    confirm_str = session.safety.generate_confirmation_string(partition)
    console.print(f"[red]⚠️  This will realign {partition}[/red]")
    user_confirm = click.prompt(f"Type '{confirm_str}' to confirm")

    if user_confirm != confirm_str:
        console.print("[red]Confirmation failed[/red]")
        sys.exit(1)

    with console.status("Aligning partition..."):
        success, message = session.platform.align_partition_4k(options)

    if success:
        console.print(f"[green]✓ {message}[/green]")
    else:
        console.print(f"[red]✗ {message}[/red]")
        sys.exit(1)


@cli.command("defrag-disk")
@click.argument("disk")
@click.option("--dry-run", is_flag=True, help="Show what would be done")
@click.pass_context
def defrag_disk(ctx: click.Context, disk: str, dry_run: bool) -> None:
    """Defragment a disk's partitions."""
    session = get_session(ctx)

    if dry_run:
        console.print(
            Panel(
                f"""[yellow]DRY RUN[/yellow]

Disk: {disk}""",
                title="Defragment Disk Plan",
            )
        )
        return

    with console.status("Defragmenting disk..."):
        success, message = session.platform.defrag_disk(disk)

    if success:
        console.print(f"[green]✓ {message}[/green]")
    else:
        console.print(f"[red]✗ {message}[/red]")
        sys.exit(1)


@cli.command("defrag-partition")
@click.argument("partition")
@click.option("--dry-run", is_flag=True, help="Show what would be done")
@click.pass_context
def defrag_partition(ctx: click.Context, partition: str, dry_run: bool) -> None:
    """Defragment a partition."""
    session = get_session(ctx)

    if dry_run:
        console.print(
            Panel(
                f"""[yellow]DRY RUN[/yellow]

Partition: {partition}""",
                title="Defragment Partition Plan",
            )
        )
        return

    with console.status("Defragmenting partition..."):
        success, message = session.platform.defrag_partition(partition)

    if success:
        console.print(f"[green]✓ {message}[/green]")
    else:
        console.print(f"[red]✗ {message}[/red]")
        sys.exit(1)


@cli.command("wipe-device")
@click.argument("target")
@click.option(
    "--method",
    type=click.Choice(["zero", "random", "dod"]),
    default="zero",
    show_default=True,
    help="Wipe method",
)
@click.option("--passes", type=int, default=1, show_default=True, help="Number of passes")
@click.option("--dry-run", is_flag=True, help="Show what would be done")
@click.pass_context
def wipe_device(
    ctx: click.Context,
    target: str,
    method: str,
    passes: int,
    dry_run: bool,
) -> None:
    """Wipe a disk or partition."""
    session = get_session(ctx)

    if session.danger_mode == DangerMode.DISABLED:
        console.print("[red]Error: Danger mode required[/red]")
        sys.exit(1)

    from diskforge.core.models import WipeOptions

    options = WipeOptions(
        target_path=target,
        method=method,
        passes=max(1, passes),
    )

    if dry_run:
        console.print(Panel(f"""[yellow]DRY RUN[/yellow]

Target: {target}
Method: {method}
Passes: {options.passes}""", title="Wipe Device Plan"))
        return

    confirm_str = session.safety.generate_confirmation_string(target)
    console.print(f"[red]⚠️  This will ERASE ALL DATA on {target}[/red]")
    user_confirm = click.prompt(f"Type '{confirm_str}' to confirm")

    if user_confirm != confirm_str:
        console.print("[red]Confirmation failed[/red]")
        sys.exit(1)

    with console.status("Wiping device..."):
        success, message = session.platform.wipe_device(options)

    if success:
        console.print(f"[green]✓ {message}[/green]")
    else:
        console.print(f"[red]✗ {message}[/red]")
        sys.exit(1)


@cli.command("wipe-system-disk")
@click.argument("disk")
@click.option(
    "--method",
    type=click.Choice(["zero", "random", "dod"]),
    default="zero",
    show_default=True,
    help="Wipe method",
)
@click.option("--passes", type=int, default=1, show_default=True, help="Number of passes")
@click.option("--dry-run", is_flag=True, help="Show what would be done")
@click.pass_context
def wipe_system_disk(
    ctx: click.Context,
    disk: str,
    method: str,
    passes: int,
    dry_run: bool,
) -> None:
    """Wipe a system disk with extra safeguards."""
    session = get_session(ctx)

    if session.danger_mode == DangerMode.DISABLED:
        console.print("[red]Error: Danger mode required[/red]")
        sys.exit(1)

    disk_info = session.platform.get_disk_info(disk)
    if disk_info is None:
        console.print(f"[red]Disk not found: {disk}[/red]")
        sys.exit(1)

    if not disk_info.is_system_disk:
        console.print(f"[red]Target is not the system disk: {disk}[/red]")
        sys.exit(1)

    from diskforge.core.models import SystemDiskWipeOptions

    options = SystemDiskWipeOptions(
        disk_path=disk,
        method=method,
        passes=max(1, passes),
        allow_system_disk=True,
        require_offline=True,
    )

    if dry_run:
        console.print(Panel(f"""[yellow]DRY RUN[/yellow]

Target: {disk}
Method: {method}
Passes: {options.passes}
Requires offline/unmounted system disk: Yes""", title="System Disk Wipe Plan"))
        success, message = session.platform.wipe_system_disk(options, dry_run=True)
        if not success:
            console.print(f"[red]Compatibility check failed: {message}[/red]")
            sys.exit(1)
        console.print(f"[green]✓ {message}[/green]")
        return

    confirm_phrase = f"WIPE SYSTEM DISK {disk}"
    console.print(f"[red]⚠️  This will ERASE THE SYSTEM DISK: {disk}[/red]")
    user_confirm = click.prompt(f"Type '{confirm_phrase}' to confirm")

    if user_confirm != confirm_phrase:
        console.print("[red]Confirmation failed[/red]")
        sys.exit(1)

    with console.status("Wiping system disk..."):
        success, message = session.platform.wipe_system_disk(options)

    if success:
        console.print(f"[green]✓ {message}[/green]")
    else:
        console.print(f"[red]✗ {message}[/red]")
        sys.exit(1)


@cli.command("secure-erase-ssd")
@click.argument("disk")
@click.option("--dry-run", is_flag=True, help="Show what would be done")
@click.pass_context
def secure_erase_ssd(
    ctx: click.Context,
    disk: str,
    dry_run: bool,
) -> None:
    """Run SSD secure erase workflow."""
    session = get_session(ctx)

    if session.danger_mode == DangerMode.DISABLED:
        console.print("[red]Error: Danger mode required[/red]")
        sys.exit(1)

    disk_info = session.platform.get_disk_info(disk)
    if disk_info is None:
        console.print(f"[red]Disk not found: {disk}[/red]")
        sys.exit(1)

    from diskforge.core.models import DiskType, SSDSecureEraseOptions

    if disk_info.disk_type not in {DiskType.SSD, DiskType.NVME}:
        console.print(f"[red]Secure erase requires an SSD or NVMe device: {disk}[/red]")
        sys.exit(1)

    options = SSDSecureEraseOptions(
        disk_path=disk,
        allow_system_disk=False,
        require_unmounted=True,
    )

    if dry_run:
        console.print(Panel(f"""[yellow]DRY RUN[/yellow]

Target: {disk}
Requires unmounted disk: Yes""", title="SSD Secure Erase Plan"))
        success, message = session.platform.secure_erase_ssd(options, dry_run=True)
        if not success:
            console.print(f"[red]Compatibility check failed: {message}[/red]")
            sys.exit(1)
        console.print(f"[green]✓ {message}[/green]")
        return

    confirm_phrase = f"SECURE ERASE {disk}"
    console.print(f"[red]⚠️  This will issue a SECURE ERASE on {disk}[/red]")
    user_confirm = click.prompt(f"Type '{confirm_phrase}' to confirm")

    if user_confirm != confirm_phrase:
        console.print("[red]Confirmation failed[/red]")
        sys.exit(1)

    with console.status("Running SSD secure erase..."):
        success, message = session.platform.secure_erase_ssd(options)

    if success:
        console.print(f"[green]✓ {message}[/green]")
    else:
        console.print(f"[red]✗ {message}[/red]")
        sys.exit(1)


@cli.command("recover-files")
@click.argument("source")
@click.option(
    "--output",
    "-o",
    type=click.Path(path_type=Path),
    required=True,
    help="Output directory for recovered files",
)
@click.option("--deep/--quick", default=True, show_default=True, help="Deep or quick scan")
@click.option("--dry-run", is_flag=True, help="Show what would be done")
@click.pass_context
def recover_files(
    ctx: click.Context,
    source: str,
    output: Path,
    deep: bool,
    dry_run: bool,
) -> None:
    """Attempt to recover deleted files."""
    session = get_session(ctx)
    json_output = ctx.obj.get("json_output", False)

    from diskforge.core.models import FileRecoveryOptions

    options = FileRecoveryOptions(
        source_path=source,
        output_path=output,
        deep_scan=deep,
    )

    if dry_run:
        console.print(
            Panel(
                f"""[yellow]DRY RUN[/yellow]

Source: {source}
Output: {output}
Scan: {"Deep" if deep else "Quick"}""",
                title="File Recovery Plan",
            )
        )
        return

    confirm_str = session.safety.generate_confirmation_string(source)
    console.print(f"[yellow]⚠️  This will scan {source} for recoverable files[/yellow]")
    user_confirm = click.prompt(f"Type '{confirm_str}' to confirm")

    if user_confirm != confirm_str:
        console.print("[red]Confirmation failed[/red]")
        sys.exit(1)

    with console.status("Running file recovery..."):
        success, message, artifacts = session.platform.recover_files(options)

    if json_output:
        import json

        click.echo(json.dumps({"success": success, "message": message, "artifacts": artifacts}, indent=2, default=str))
        if not success:
            sys.exit(1)
        return

    if success:
        console.print(f"[green]✓ {message}[/green]")
        if artifacts:
            console.print("\nRecovery artifacts:")
            for key, path in artifacts.items():
                console.print(f"  {key}: {path}")
    else:
        console.print(f"[red]✗ {message}[/red]")
        sys.exit(1)


@cli.command("shred")
@click.argument("targets", nargs=-1, required=True)
@click.option("--passes", type=int, default=3, show_default=True, help="Number of overwrite passes")
@click.option("--no-zero", is_flag=True, help="Skip zero-fill on final pass")
@click.option("--follow-symlinks", is_flag=True, help="Follow symlinks when shredding")
@click.option("--dry-run", is_flag=True, help="Show what would be done")
@click.pass_context
def shred(
    ctx: click.Context,
    targets: tuple[str, ...],
    passes: int,
    no_zero: bool,
    follow_symlinks: bool,
    dry_run: bool,
) -> None:
    """Securely shred files or folders."""
    session = get_session(ctx)

    if session.danger_mode == DangerMode.DISABLED:
        console.print("[red]Error: Danger mode required[/red]")
        sys.exit(1)

    from diskforge.core.models import ShredOptions

    options = ShredOptions(
        targets=list(targets),
        passes=max(1, passes),
        zero_fill=not no_zero,
        follow_symlinks=follow_symlinks,
    )

    if dry_run:
        console.print(
            Panel(
                f"""[yellow]DRY RUN[/yellow]

Targets: {", ".join(targets)}
Passes: {options.passes}
Zero-fill: {"No" if no_zero else "Yes"}
Follow symlinks: {"Yes" if follow_symlinks else "No"}""",
                title="Shred Plan",
            )
        )
        return

    confirm_target = targets[0] if len(targets) == 1 else f"{targets[0]} (+{len(targets) - 1} more)"
    confirm_str = session.safety.generate_confirmation_string(confirm_target)
    console.print(f"[red]⚠️  This will PERMANENTLY DELETE {confirm_target}[/red]")
    user_confirm = click.prompt(f"Type '{confirm_str}' to confirm")

    if user_confirm != confirm_str:
        console.print("[red]Confirmation failed[/red]")
        sys.exit(1)

    with console.status("Shredding files..."):
        success, message = session.platform.shred_files(options)

    if success:
        console.print(f"[green]✓ {message}[/green]")
    else:
        console.print(f"[red]✗ {message}[/red]")
        sys.exit(1)


@cli.command("partition-recovery")
@click.argument("disk")
@click.option(
    "--output",
    "-o",
    type=click.Path(path_type=Path),
    help="Output directory for recovery artifacts",
)
@click.option("--quick/--full", default=True, help="Quick or full scan")
@click.option("--dry-run", is_flag=True, help="Show what would be done")
@click.pass_context
def partition_recovery(
    ctx: click.Context,
    disk: str,
    output: Path | None,
    quick: bool,
    dry_run: bool,
) -> None:
    """Attempt to recover partitions on a disk."""
    session = get_session(ctx)
    json_output = ctx.obj.get("json_output", False)

    from diskforge.core.models import PartitionRecoveryOptions

    options = PartitionRecoveryOptions(
        disk_path=disk,
        output_path=output,
        quick_scan=quick,
    )

    if dry_run:
        console.print(Panel(f"""[yellow]DRY RUN[/yellow]

Disk: {disk}
Output: {output or "(none)"}
Scan: {"Quick" if quick else "Full"}""", title="Partition Recovery Plan"))
        return

    with console.status("Running partition recovery..."):
        success, message, artifacts = session.platform.recover_partitions(options)

    if json_output:
        import json

        click.echo(json.dumps({"success": success, "message": message, "artifacts": artifacts}, indent=2, default=str))
        if not success:
            sys.exit(1)
        return

    if success:
        console.print(f"[green]✓ {message}[/green]")
        if artifacts:
            console.print("\nRecovery artifacts:")
            for key, path in artifacts.items():
                console.print(f"  {key}: {path}")
    else:
        console.print(f"[red]✗ {message}[/red]")
        sys.exit(1)


cli.add_command(partition_recovery, "recover-partitions")


@cli.command("convert-mbr-gpt")
@click.argument("disk")
@click.option(
    "--to",
    "target_style",
    type=click.Choice(["gpt", "mbr"], case_sensitive=False),
    required=True,
    help="Target partition style",
)
@click.option("--dry-run", is_flag=True, help="Show what would be done")
@click.pass_context
def convert_mbr_gpt(
    ctx: click.Context,
    disk: str,
    target_style: str,
    dry_run: bool,
) -> None:
    """Convert disk partition style (MBR/GPT)."""
    session = get_session(ctx)

    if session.danger_mode == DangerMode.DISABLED:
        console.print("[red]Error: Danger mode required[/red]")
        sys.exit(1)

    from diskforge.core.models import ConvertDiskOptions, PartitionStyle

    style_map = {"gpt": PartitionStyle.GPT, "mbr": PartitionStyle.MBR}

    options = ConvertDiskOptions(
        disk_path=disk,
        target_style=style_map[target_style.lower()],
    )

    if dry_run:
        console.print(Panel(f"""[yellow]DRY RUN[/yellow]

Disk: {disk}
Target style: {options.target_style.name}""", title="Convert Partition Style Plan"))
        return

    confirm_str = session.safety.generate_confirmation_string(disk)
    console.print(f"[red]⚠️  This will convert {disk} to {options.target_style.name}[/red]")
    user_confirm = click.prompt(f"Type '{confirm_str}' to confirm")

    if user_confirm != confirm_str:
        console.print("[red]Confirmation failed[/red]")
        sys.exit(1)

    with console.status("Converting partition style..."):
        success, message = session.platform.convert_disk_partition_style(options)

    if success:
        console.print(f"[green]✓ {message}[/green]")
    else:
        console.print(f"[red]✗ {message}[/red]")
        sys.exit(1)


@cli.command("convert-system-mbr-gpt")
@click.argument("disk")
@click.option(
    "--to",
    "target_style",
    type=click.Choice(["gpt", "mbr"], case_sensitive=False),
    required=True,
    help="Target partition style",
)
@click.option(
    "--allow-full-os/--no-allow-full-os",
    default=True,
    help="Allow conversion while the OS is running (Windows)",
)
@click.option("--dry-run", is_flag=True, help="Show what would be done")
@click.pass_context
def convert_system_mbr_gpt(
    ctx: click.Context,
    disk: str,
    target_style: str,
    allow_full_os: bool,
    dry_run: bool,
) -> None:
    """Convert the system disk partition style (MBR/GPT) with safety checks."""
    session = get_session(ctx)

    if session.danger_mode == DangerMode.DISABLED:
        console.print("[red]Error: Danger mode required[/red]")
        sys.exit(1)

    from diskforge.core.models import ConvertSystemDiskOptions, PartitionStyle

    style_map = {"gpt": PartitionStyle.GPT, "mbr": PartitionStyle.MBR}

    options = ConvertSystemDiskOptions(
        disk_path=disk,
        target_style=style_map[target_style.lower()],
        allow_full_os=allow_full_os,
    )

    if dry_run:
        console.print(Panel(f"""[yellow]DRY RUN[/yellow]

Disk: {disk}
Target style: {options.target_style.name}
Allow full OS: {allow_full_os}""", title="Convert System Disk Plan"))
        return

    confirm_str = session.safety.generate_confirmation_string(disk)
    console.print(f"[red]⚠️  This will convert system disk {disk} to {options.target_style.name}[/red]")
    user_confirm = click.prompt(f"Type '{confirm_str}' to confirm")

    if user_confirm != confirm_str:
        console.print("[red]Confirmation failed[/red]")
        sys.exit(1)

    with console.status("Converting system disk partition style..."):
        success, message = session.platform.convert_system_disk_partition_style(options)

    if success:
        console.print(f"[green]✓ {message}[/green]")
    else:
        console.print(f"[red]✗ {message}[/red]")
        sys.exit(1)


@cli.command("convert-filesystem")
@click.argument("partition")
@click.option(
    "--to",
    "target_fs",
    type=click.Choice(["ntfs", "fat32"], case_sensitive=False),
    required=True,
    help="Target filesystem",
)
@click.option(
    "--allow-format",
    is_flag=True,
    help="Allow formatting if conversion requires it",
)
@click.option("--dry-run", is_flag=True, help="Show what would be done")
@click.pass_context
def convert_filesystem(
    ctx: click.Context,
    partition: str,
    target_fs: str,
    allow_format: bool,
    dry_run: bool,
) -> None:
    """Convert a partition filesystem between NTFS and FAT32."""
    session = get_session(ctx)

    if session.danger_mode == DangerMode.DISABLED:
        console.print("[red]Error: Danger mode required[/red]")
        sys.exit(1)

    from diskforge.core.models import ConvertFilesystemOptions, FileSystem

    fs_map = {"ntfs": FileSystem.NTFS, "fat32": FileSystem.FAT32}

    options = ConvertFilesystemOptions(
        partition_path=partition,
        target_filesystem=fs_map[target_fs.lower()],
        allow_format=allow_format,
    )

    if dry_run:
        console.print(Panel(f"""[yellow]DRY RUN[/yellow]

Partition: {partition}
Target filesystem: {options.target_filesystem.value}
Allow format: {allow_format}""", title="Filesystem Conversion Plan"))
        return

    confirm_str = session.safety.generate_confirmation_string(partition)
    console.print(f"[red]⚠️  This will convert {partition} to {options.target_filesystem.value}[/red]")
    user_confirm = click.prompt(f"Type '{confirm_str}' to confirm")

    if user_confirm != confirm_str:
        console.print("[red]Confirmation failed[/red]")
        sys.exit(1)

    with console.status("Converting filesystem..."):
        success, message = session.platform.convert_partition_filesystem(options)

    if success:
        console.print(f"[green]✓ {message}[/green]")
    else:
        console.print(f"[red]✗ {message}[/red]")
        sys.exit(1)


@cli.command("convert-partition-role")
@click.argument("partition")
@click.option(
    "--to",
    "target_role",
    type=click.Choice(["primary", "logical"], case_sensitive=False),
    required=True,
    help="Target partition role",
)
@click.option("--dry-run", is_flag=True, help="Show what would be done")
@click.pass_context
def convert_partition_role(
    ctx: click.Context,
    partition: str,
    target_role: str,
    dry_run: bool,
) -> None:
    """Convert a partition between primary and logical."""
    session = get_session(ctx)

    if session.danger_mode == DangerMode.DISABLED:
        console.print("[red]Error: Danger mode required[/red]")
        sys.exit(1)

    from diskforge.core.models import ConvertPartitionRoleOptions, PartitionRole

    role_map = {"primary": PartitionRole.PRIMARY, "logical": PartitionRole.LOGICAL}

    options = ConvertPartitionRoleOptions(
        partition_path=partition,
        target_role=role_map[target_role.lower()],
    )

    if dry_run:
        console.print(Panel(f"""[yellow]DRY RUN[/yellow]

Partition: {partition}
Target role: {options.target_role.name}""", title="Partition Role Conversion Plan"))
        return

    confirm_str = session.safety.generate_confirmation_string(partition)
    console.print(f"[red]⚠️  This will convert {partition} to {options.target_role.name}[/red]")
    user_confirm = click.prompt(f"Type '{confirm_str}' to confirm")

    if user_confirm != confirm_str:
        console.print("[red]Confirmation failed[/red]")
        sys.exit(1)

    with console.status("Converting partition role..."):
        success, message = session.platform.convert_partition_role(options)

    if success:
        console.print(f"[green]✓ {message}[/green]")
    else:
        console.print(f"[red]✗ {message}[/red]")
        sys.exit(1)


@cli.command("convert-disk-layout")
@click.argument("disk")
@click.option(
    "--to",
    "target_layout",
    type=click.Choice(["basic", "dynamic"], case_sensitive=False),
    required=True,
    help="Target disk layout",
)
@click.option("--dry-run", is_flag=True, help="Show what would be done")
@click.pass_context
def convert_disk_layout(
    ctx: click.Context,
    disk: str,
    target_layout: str,
    dry_run: bool,
) -> None:
    """Convert a disk between basic and dynamic layouts."""
    session = get_session(ctx)

    if session.danger_mode == DangerMode.DISABLED:
        console.print("[red]Error: Danger mode required[/red]")
        sys.exit(1)

    from diskforge.core.models import ConvertDiskLayoutOptions, DiskLayout

    layout_map = {"basic": DiskLayout.BASIC, "dynamic": DiskLayout.DYNAMIC}

    options = ConvertDiskLayoutOptions(
        disk_path=disk,
        target_layout=layout_map[target_layout.lower()],
    )

    if dry_run:
        console.print(Panel(f"""[yellow]DRY RUN[/yellow]

Disk: {disk}
Target layout: {options.target_layout.name}""", title="Disk Layout Conversion Plan"))
        return

    confirm_str = session.safety.generate_confirmation_string(disk)
    console.print(f"[red]⚠️  This will convert {disk} to {options.target_layout.name}[/red]")
    user_confirm = click.prompt(f"Type '{confirm_str}' to confirm")

    if user_confirm != confirm_str:
        console.print("[red]Confirmation failed[/red]")
        sys.exit(1)

    with console.status("Converting disk layout..."):
        success, message = session.platform.convert_disk_layout(options)

    if success:
        console.print(f"[green]✓ {message}[/green]")
    else:
        console.print(f"[red]✗ {message}[/red]")
        sys.exit(1)


@cli.command("migrate-system")
@click.argument("source")
@click.argument("target")
@click.option("--dry-run", is_flag=True, help="Show what would be done")
@click.pass_context
def migrate_system(
    ctx: click.Context,
    source: str,
    target: str,
    dry_run: bool,
) -> None:
    """Migrate OS/system to another disk."""
    session = get_session(ctx)

    if session.danger_mode == DangerMode.DISABLED:
        console.print("[red]Error: Danger mode required[/red]")
        sys.exit(1)

    from diskforge.core.models import MigrationOptions

    options = MigrationOptions(
        source_disk_path=source,
        target_disk_path=target,
    )

    if dry_run:
        console.print(Panel(f"""[yellow]DRY RUN[/yellow]

Source: {source}
Target: {target}""", title="System Migration Plan"))
        return

    confirm_str = session.safety.generate_confirmation_string(target)
    console.print(f"[red]⚠️  This will DESTROY ALL DATA on {target}[/red]")
    user_confirm = click.prompt(f"Type '{confirm_str}' to confirm")

    if user_confirm != confirm_str:
        console.print("[red]Confirmation failed[/red]")
        sys.exit(1)

    with console.status("Migrating system disk..."):
        success, message = session.platform.migrate_system(options)

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


@cli.command("integrate-winre")
@click.argument("source", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--mount-path",
    type=click.Path(path_type=Path),
    default=Path("C:\\WinRE"),
    show_default=True,
    help="Temporary mount path for WinRE image",
)
@click.option(
    "--target-subdir",
    default="DiskForge",
    show_default=True,
    help="Folder name inside WinRE System32",
)
@click.option("--dry-run", is_flag=True, help="Show what would be done")
@click.pass_context
def integrate_winre(
    ctx: click.Context,
    source: Path,
    mount_path: Path,
    target_subdir: str,
    dry_run: bool,
) -> None:
    """Integrate DiskForge scripts into Windows Recovery Environment."""
    session = get_session(ctx)
    require_platform(session, "windows", "WinRE integration")

    from diskforge.core.models import WinREIntegrationOptions

    options = WinREIntegrationOptions(
        source_path=source,
        mount_path=mount_path,
        target_subdir=target_subdir,
    )

    if dry_run:
        console.print(Panel(f"""[yellow]DRY RUN[/yellow]

Source: {source}
Mount path: {mount_path}
Target subdir: {target_subdir}""", title="WinRE Integration Plan"))
        return

    with console.status("Integrating into WinRE..."):
        success, message, artifacts = session.platform.integrate_recovery_environment(options)

    if success:
        console.print(f"[green]✓ {message}[/green]")
        if artifacts:
            console.print("\nArtifacts:")
            for key, value in artifacts.items():
                console.print(f"  {key}: {value}")
    else:
        console.print(f"[red]✗ {message}[/red]")
        sys.exit(1)


@cli.command("boot-repair")
@click.option(
    "--system-root",
    type=click.Path(path_type=Path),
    default=Path("C:\\Windows"),
    show_default=True,
    help="Windows system root used for BCDBoot",
)
@click.option("--fix-mbr/--no-fix-mbr", default=True, show_default=True, help="Run bootrec /fixmbr")
@click.option("--fix-boot/--no-fix-boot", default=True, show_default=True, help="Run bootrec /fixboot")
@click.option("--rebuild-bcd/--no-rebuild-bcd", default=True, show_default=True, help="Rebuild BCD store")
@click.option("--dry-run", is_flag=True, help="Show what would be done")
@click.pass_context
def boot_repair(
    ctx: click.Context,
    system_root: Path,
    fix_mbr: bool,
    fix_boot: bool,
    rebuild_bcd: bool,
    dry_run: bool,
) -> None:
    """Run boot repair commands (Windows/WinRE)."""
    session = get_session(ctx)
    require_platform(session, "windows", "Boot repair")

    if session.danger_mode == DangerMode.DISABLED:
        console.print("[red]Error: Danger mode required[/red]")
        sys.exit(1)

    from diskforge.core.models import BootRepairOptions

    options = BootRepairOptions(
        system_root=system_root,
        fix_mbr=fix_mbr,
        fix_boot=fix_boot,
        rebuild_bcd=rebuild_bcd,
    )

    if dry_run:
        console.print(Panel(f"""[yellow]DRY RUN[/yellow]

System root: {system_root}
Fix MBR: {fix_mbr}
Fix boot: {fix_boot}
Rebuild BCD: {rebuild_bcd}""", title="Boot Repair Plan"))
        return

    confirm_str = session.safety.generate_confirmation_string("boot-repair")
    console.print("[red]⚠️  This will modify boot configuration[/red]")
    user_confirm = click.prompt(f"Type '{confirm_str}' to confirm")

    if user_confirm != confirm_str:
        console.print("[red]Confirmation failed[/red]")
        sys.exit(1)

    with console.status("Running boot repair..."):
        success, message, artifacts = session.platform.repair_boot(options)

    if success:
        console.print(f"[green]✓ {message}[/green]")
        if artifacts:
            console.print("\nCommand output:")
            for key, value in artifacts.items():
                console.print(f"  {key}: {value.get('stderr') or value.get('stdout')}")
    else:
        console.print(f"[red]✗ {message}[/red]")
        sys.exit(1)


@cli.command("rebuild-mbr")
@click.option("--fix-boot/--no-fix-boot", default=True, show_default=True, help="Run bootrec /fixboot")
@click.option("--dry-run", is_flag=True, help="Show what would be done")
@click.pass_context
def rebuild_mbr(ctx: click.Context, fix_boot: bool, dry_run: bool) -> None:
    """Rebuild the master boot record (Windows/WinRE)."""
    session = get_session(ctx)
    require_platform(session, "windows", "MBR rebuild")

    if session.danger_mode == DangerMode.DISABLED:
        console.print("[red]Error: Danger mode required[/red]")
        sys.exit(1)

    from diskforge.core.models import RebuildMBROptions

    options = RebuildMBROptions(fix_boot=fix_boot)

    if dry_run:
        console.print(Panel(f"""[yellow]DRY RUN[/yellow]

Fix boot: {fix_boot}""", title="MBR Rebuild Plan"))
        return

    confirm_str = session.safety.generate_confirmation_string("mbr")
    console.print("[red]⚠️  This will rewrite the MBR boot code[/red]")
    user_confirm = click.prompt(f"Type '{confirm_str}' to confirm")

    if user_confirm != confirm_str:
        console.print("[red]Confirmation failed[/red]")
        sys.exit(1)

    with console.status("Rebuilding MBR..."):
        success, message = session.platform.rebuild_mbr(options)

    if success:
        console.print(f"[green]✓ {message}[/green]")
    else:
        console.print(f"[red]✗ {message}[/red]")
        sys.exit(1)


@cli.command("uefi-boot-options")
@click.option(
    "--action",
    type=click.Choice(["list", "set-default"], case_sensitive=False),
    default="list",
    show_default=True,
    help="UEFI boot option action",
)
@click.option("--identifier", help="Identifier for set-default action")
@click.option("--dry-run", is_flag=True, help="Show what would be done")
@click.pass_context
def uefi_boot_options(
    ctx: click.Context,
    action: str,
    identifier: str | None,
    dry_run: bool,
) -> None:
    """List or set UEFI firmware boot options (Windows only)."""
    session = get_session(ctx)
    require_platform(session, "windows", "UEFI boot option manager")

    from diskforge.core.models import UEFIBootOptions

    options = UEFIBootOptions(action=action, identifier=identifier)

    if dry_run:
        console.print(Panel(f"""[yellow]DRY RUN[/yellow]

Action: {action}
Identifier: {identifier or "(none)"}""", title="UEFI Boot Options Plan"))
        return

    with console.status("Managing UEFI boot options..."):
        success, message, artifacts = session.platform.manage_uefi_boot_options(options)

    if success:
        console.print(f"[green]✓ {message}[/green]")
        output = artifacts.get("output")
        if output:
            console.print("\nOutput:")
            console.print(output)
    else:
        console.print(f"[red]✗ {message}[/red]")
        sys.exit(1)


@cli.command("windows-to-go")
@click.argument("image", type=click.Path(exists=True, path_type=Path))
@click.argument("target_drive")
@click.option("--index", "apply_index", default=1, show_default=True, help="Image index to apply")
@click.option("--label", help="Optional label for the target drive")
@click.option("--dry-run", is_flag=True, help="Show what would be done")
@click.pass_context
def windows_to_go(
    ctx: click.Context,
    image: Path,
    target_drive: str,
    apply_index: int,
    label: str | None,
    dry_run: bool,
) -> None:
    """Create a Windows To Go workspace on the target drive."""
    session = get_session(ctx)
    require_platform(session, "windows", "Windows To Go")

    if session.danger_mode == DangerMode.DISABLED:
        console.print("[red]Error: Danger mode required[/red]")
        sys.exit(1)

    from diskforge.core.models import WindowsToGoOptions

    options = WindowsToGoOptions(
        image_path=image,
        target_drive=target_drive,
        apply_index=apply_index,
        label=label,
    )

    if dry_run:
        console.print(Panel(f"""[yellow]DRY RUN[/yellow]

Image: {image}
Target drive: {target_drive}
Index: {apply_index}
Label: {label or "(none)"}""", title="Windows To Go Plan"))
        return

    confirm_str = session.safety.generate_confirmation_string(target_drive)
    console.print("[red]⚠️  This will deploy Windows to the target drive[/red]")
    user_confirm = click.prompt(f"Type '{confirm_str}' to confirm")

    if user_confirm != confirm_str:
        console.print("[red]Confirmation failed[/red]")
        sys.exit(1)

    with console.status("Creating Windows To Go workspace..."):
        success, message, artifacts = session.platform.create_windows_to_go(options)

    if success:
        console.print(f"[green]✓ {message}[/green]")
        if artifacts:
            console.print("\nCommand output:")
            for key, value in artifacts.items():
                console.print(f"  {key}: {value.get('stderr') or value.get('stdout')}")
    else:
        console.print(f"[red]✗ {message}[/red]")
        sys.exit(1)


@cli.command("reset-windows-password")
@click.option("--user", "username", required=True, help="Windows account name")
@click.option("--new-password", prompt=True, hide_input=True, confirmation_prompt=True)
@click.option("--dry-run", is_flag=True, help="Show what would be done")
@click.pass_context
def reset_windows_password(
    ctx: click.Context,
    username: str,
    new_password: str,
    dry_run: bool,
) -> None:
    """Reset a Windows local account password."""
    session = get_session(ctx)
    require_platform(session, "windows", "Windows password reset")

    if session.danger_mode == DangerMode.DISABLED:
        console.print("[red]Error: Danger mode required[/red]")
        sys.exit(1)

    from diskforge.core.models import WindowsPasswordResetOptions

    options = WindowsPasswordResetOptions(username=username, new_password=new_password)

    if dry_run:
        console.print(Panel(f"""[yellow]DRY RUN[/yellow]

User: {username}""", title="Password Reset Plan"))
        return

    confirm_str = session.safety.generate_confirmation_string(username)
    console.print("[red]⚠️  This will reset the password for the selected account[/red]")
    user_confirm = click.prompt(f"Type '{confirm_str}' to confirm")

    if user_confirm != confirm_str:
        console.print("[red]Confirmation failed[/red]")
        sys.exit(1)

    with console.status("Resetting Windows password..."):
        success, message = session.platform.reset_windows_password(options)

    if success:
        console.print(f"[green]✓ {message}[/green]")
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


def _require_danger_mode(session: Session, operation_name: str) -> None:
    if session.danger_mode == DangerMode.DISABLED:
        console.print(
            f"[red]{operation_name} requires Danger Mode.[/red] "
            "Re-run with --danger-mode and confirm.",
        )
        sys.exit(1)


def _confirm_destructive(session: Session, target: str) -> None:
    confirm_str = session.safety.generate_confirmation_string(target)
    confirm = click.prompt(
        f"Type '{confirm_str}' to continue",
        default="",
        show_default=False,
    )
    if confirm.strip() != confirm_str:
        console.print("[red]Confirmation mismatch. Operation cancelled.[/red]")
        sys.exit(1)


@cli.command("free-space")
@click.option("--root", "roots", multiple=True, type=click.Path(path_type=Path))
@click.option("--exclude", "excludes", multiple=True, help="Glob pattern to exclude")
@click.option("--large-min-size", default="512M", help="Large file threshold (e.g., 1G)")
@click.option("--duplicate-min-size", default="32M", help="Duplicate scan minimum size")
@click.option("--junk-max-files", type=int, default=500, help="Maximum junk files to include")
@click.pass_context
def free_space(
    ctx: click.Context,
    roots: tuple[Path, ...],
    excludes: tuple[str, ...],
    large_min_size: str,
    duplicate_min_size: str,
    junk_max_files: int,
) -> None:
    """Summarize reclaimable space."""
    session = get_session(ctx)
    json_output = ctx.obj.get("json_output", False)
    large_min = parse_size(large_min_size) or 0
    duplicate_min = parse_size(duplicate_min_size) or 0
    options = FreeSpaceOptions(
        roots=[str(root) for root in roots],
        exclude_patterns=list(excludes),
        junk_max_files=junk_max_files,
        large_min_size_bytes=large_min,
        duplicate_min_size_bytes=duplicate_min,
    )
    report = session.platform.scan_free_space(options)

    if json_output:
        import json

        click.echo(json.dumps(report.to_dict(), indent=2, default=str))
        return

    panel = Panel(
        f"""[cyan]Roots:[/cyan] {", ".join(report.roots)}
[cyan]Total Reclaimable:[/cyan] {humanize.naturalsize(report.total_reclaimable_bytes, binary=True)}
[cyan]Junk:[/cyan] {humanize.naturalsize(report.junk_bytes, binary=True)}
[cyan]Large Files:[/cyan] {humanize.naturalsize(report.large_files_bytes, binary=True)}
[cyan]Duplicates:[/cyan] {humanize.naturalsize(report.duplicate_bytes, binary=True)}""",
        title="Free Space Summary",
    )
    console.print(panel)


@cli.command("junk-scan")
@click.option("--root", "roots", multiple=True, type=click.Path(path_type=Path))
@click.option("--exclude", "excludes", multiple=True, help="Glob pattern to exclude")
@click.option("--max-files", type=int, default=500, help="Maximum junk files to include")
@click.pass_context
def junk_scan(
    ctx: click.Context,
    roots: tuple[Path, ...],
    excludes: tuple[str, ...],
    max_files: int,
) -> None:
    """Scan for junk files."""
    session = get_session(ctx)
    json_output = ctx.obj.get("json_output", False)
    options = JunkCleanupOptions(
        roots=[str(root) for root in roots],
        exclude_patterns=list(excludes),
        max_files=max_files,
    )
    scan = session.platform.scan_junk_files(options)

    if json_output:
        import json

        click.echo(json.dumps(scan.to_dict(), indent=2, default=str))
        return

    table = Table(title="Junk Files")
    table.add_column("Path", style="cyan")
    table.add_column("Category", style="magenta")
    table.add_column("Size", style="green")
    for item in scan.files:
        table.add_row(item.path, item.category, humanize.naturalsize(item.size_bytes, binary=True))
    console.print(table)
    console.print(f"Total: {humanize.naturalsize(scan.total_size_bytes, binary=True)}")


@cli.command("junk-clean")
@click.option("--root", "roots", multiple=True, type=click.Path(path_type=Path))
@click.option("--exclude", "excludes", multiple=True, help="Glob pattern to exclude")
@click.option("--max-files", type=int, default=500, help="Maximum junk files to include")
@click.pass_context
def junk_clean(
    ctx: click.Context,
    roots: tuple[Path, ...],
    excludes: tuple[str, ...],
    max_files: int,
) -> None:
    """Clean junk files."""
    session = get_session(ctx)
    _require_danger_mode(session, "Junk cleanup")
    target_label = roots[0] if roots else Path.home()
    _confirm_destructive(session, str(target_label))

    json_output = ctx.obj.get("json_output", False)
    options = JunkCleanupOptions(
        roots=[str(root) for root in roots],
        exclude_patterns=list(excludes),
        max_files=max_files,
    )
    result = session.platform.cleanup_junk_files(options)

    if json_output:
        import json

        click.echo(json.dumps(result.to_dict(), indent=2, default=str))
        return

    panel = Panel(
        f"""[cyan]Removed:[/cyan] {len(result.removed_files)}
[cyan]Failed:[/cyan] {len(result.failed_files)}
[cyan]Freed:[/cyan] {humanize.naturalsize(result.freed_bytes, binary=True)}""",
        title="Junk Cleanup",
    )
    console.print(panel)


@cli.command("large-files")
@click.option("--root", "roots", multiple=True, type=click.Path(path_type=Path))
@click.option("--exclude", "excludes", multiple=True, help="Glob pattern to exclude")
@click.option("--min-size", default="1G", help="Minimum file size")
@click.option("--max-results", type=int, default=50, help="Maximum results to return")
@click.option("--remove", is_flag=True, help="Remove discovered files")
@click.pass_context
def large_files(
    ctx: click.Context,
    roots: tuple[Path, ...],
    excludes: tuple[str, ...],
    min_size: str,
    max_results: int,
    remove: bool,
) -> None:
    """Find large files."""
    session = get_session(ctx)
    json_output = ctx.obj.get("json_output", False)
    min_size_bytes = parse_size(min_size) or 0
    options = LargeFileScanOptions(
        roots=[str(root) for root in roots],
        exclude_patterns=list(excludes),
        min_size_bytes=min_size_bytes,
        max_results=max_results,
    )
    scan = session.platform.scan_large_files(options)

    removal_result = None
    if remove and scan.files:
        _require_danger_mode(session, "Large file removal")
        target_label = roots[0] if roots else Path.home()
        _confirm_destructive(session, str(target_label))
        removal_result = session.platform.remove_large_files(
            FileRemovalOptions(paths=[entry.path for entry in scan.files])
        )

    if json_output:
        import json

        payload = {"scan": scan.to_dict()}
        if removal_result:
            payload["removal"] = removal_result.to_dict()
        click.echo(json.dumps(payload, indent=2, default=str))
        return

    table = Table(title="Large Files")
    table.add_column("Path", style="cyan")
    table.add_column("Size", style="green")
    for entry in scan.files:
        table.add_row(entry.path, humanize.naturalsize(entry.size_bytes, binary=True))
    console.print(table)
    console.print(f"Total size: {humanize.naturalsize(scan.total_size_bytes, binary=True)}")
    if removal_result:
        console.print(
            Panel(
                removal_result.message,
                title="Removal Summary",
            )
        )


@cli.command("duplicates")
@click.option("--root", "roots", multiple=True, type=click.Path(path_type=Path))
@click.option("--exclude", "excludes", multiple=True, help="Glob pattern to exclude")
@click.option("--min-size", default="32M", help="Minimum file size")
@click.option("--remove", is_flag=True, help="Remove duplicates (keep one copy)")
@click.pass_context
def duplicates(
    ctx: click.Context,
    roots: tuple[Path, ...],
    excludes: tuple[str, ...],
    min_size: str,
    remove: bool,
) -> None:
    """Detect duplicate files."""
    session = get_session(ctx)
    json_output = ctx.obj.get("json_output", False)
    min_size_bytes = parse_size(min_size) or 0
    options = DuplicateScanOptions(
        roots=[str(root) for root in roots],
        exclude_patterns=list(excludes),
        min_size_bytes=min_size_bytes,
    )
    scan = session.platform.scan_duplicate_files(options)

    removal_result = None
    if remove and scan.duplicate_groups:
        _require_danger_mode(session, "Duplicate removal")
        target_label = roots[0] if roots else Path.home()
        _confirm_destructive(session, str(target_label))
        removal_result = session.platform.remove_duplicate_files(
            DuplicateRemovalOptions(duplicate_groups=scan.duplicate_groups)
        )

    if json_output:
        import json

        payload = {"scan": scan.to_dict()}
        if removal_result:
            payload["removal"] = removal_result.to_dict()
        click.echo(json.dumps(payload, indent=2, default=str))
        return

    console.print(
        Panel(
            f"Duplicate groups: {len(scan.duplicate_groups)}\n"
            f"Wasted: {humanize.naturalsize(scan.total_wasted_bytes, binary=True)}",
            title="Duplicate Scan",
        )
    )
    if removal_result:
        console.print(Panel(removal_result.message, title="Removal Summary"))


@cli.command("move-app")
@click.option("--source", "source_path", required=True, type=click.Path(path_type=Path))
@click.option("--destination", "destination_root", required=True, type=click.Path(path_type=Path))
@click.pass_context
def move_app(ctx: click.Context, source_path: Path, destination_root: Path) -> None:
    """Move an application directory to another drive."""
    session = get_session(ctx)
    _require_danger_mode(session, "Move application")
    _confirm_destructive(session, str(source_path))

    json_output = ctx.obj.get("json_output", False)
    result = session.platform.move_application(
        MoveApplicationOptions(
            source_path=str(source_path),
            destination_root=str(destination_root),
        )
    )

    if json_output:
        import json

        click.echo(json.dumps(result.to_dict(), indent=2, default=str))
        return

    panel = Panel(
        f"""[cyan]Success:[/cyan] {"Yes" if result.success else "No"}
[cyan]Message:[/cyan] {result.message}
[cyan]Destination:[/cyan] {result.destination_path}
[cyan]Moved:[/cyan] {humanize.naturalsize(result.bytes_moved, binary=True)}""",
        title="Move Application",
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
