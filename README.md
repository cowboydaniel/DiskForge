# DiskForge

A production-grade cross-platform disk management application for Windows 11+ and modern Linux distributions.

## Features

- **Disk/Partition Inventory**: View all disks, partitions, filesystems, sizes, mount points, and flags with auto-refresh
- **Partition Management**: Create, delete, and format partitions with safety guardrails
- **Disk/Partition Cloning**: Block-level cloning with verification support
- **Image Backup/Restore**: Create compressed disk images with checksum verification
- **Bootable Rescue Media**: Create rescue ISO (Linux) or WinRE package (Windows)
- **Plugin System**: Extensible architecture for custom operations

## Safety Features

- **Read-only by default**: Destructive operations require explicit "Danger Mode" activation
- **Typed confirmation**: Destructive actions require typing the target device identifier
- **Preflight checks**: Verify power status, target size, mount status before operations
- **System disk protection**: Prevents accidental modification of system disks
- **Structured logging**: Complete audit trail with session reports

## Installation

### Using Poetry (recommended)

```bash
# Install Poetry if not already installed
curl -sSL https://install.python-poetry.org | python3 -

# Clone and install
git clone https://github.com/diskforge/diskforge.git
cd diskforge
poetry install

# Run the GUI
poetry run diskforge-gui

# Or use the CLI
poetry run diskforge --help
```

### Using pip

```bash
pip install diskforge
```

## Usage

### GUI Mode

```bash
diskforge-gui
```

### CLI Mode

```bash
# List all disks
diskforge list

# Show disk details
diskforge info /dev/sda

# Create partition (requires danger mode)
diskforge --danger-mode create-partition /dev/sdb --filesystem ext4 --size 10G

# Clone a disk
diskforge --danger-mode clone /dev/sda /dev/sdb --verify

# Create backup image
diskforge backup /dev/sda1 /backup/sda1.img.zst --compression zstd

# Restore image
diskforge --danger-mode restore /backup/sda1.img.zst /dev/sdb1

# Create rescue media
diskforge rescue /output/rescue
```

### Danger Mode

Destructive operations require Danger Mode to be enabled:

```bash
# Enable via command line
diskforge --danger-mode <command>

# You will be prompted to type: "I understand the risks"
```

In the GUI, use Tools > Toggle Danger Mode.

## Platform Support

### Linux

Uses standard tools:
- `lsblk`, `blkid`: Disk inventory
- `sfdisk`, `parted`: Partition management
- `mkfs.*`: Filesystem creation
- `dd`: Cloning and imaging
- `resize2fs`, `xfs_growfs`, `btrfs`: Filesystem resizing

### Windows

Uses:
- PowerShell `Get-Disk`, `Get-Partition`, `Get-Volume`
- `diskpart` for partition management
- Native file operations for cloning/imaging

## Requirements

- Python 3.12+
- PySide6 (for GUI)
- Administrative privileges for disk operations

### Linux Dependencies

Most disk tools are pre-installed. For full functionality:

```bash
# Debian/Ubuntu
sudo apt install parted util-linux xfsprogs btrfs-progs

# Fedora/RHEL
sudo dnf install parted util-linux xfsprogs btrfs-progs
```

### Windows Dependencies

No additional dependencies required - uses built-in Windows tools.

## Development

### Setup

```bash
# Clone repository
git clone https://github.com/diskforge/diskforge.git
cd diskforge

# Install dev dependencies
make install-dev

# Run tests
make test

# Run linter
make lint
```

### Running Tests

```bash
# All tests
make test

# Unit tests only (no admin required)
make test-unit

# Integration tests
make test-integration

# GUI tests
make test-gui

# With coverage
make test-coverage
```

### Project Structure

```
diskforge/
├── src/diskforge/
│   ├── core/           # Business logic, job runner, safety
│   ├── platform/       # OS-specific implementations
│   │   ├── linux/      # Linux backend using system tools
│   │   └── windows/    # Windows backend using PowerShell
│   ├── plugins/        # Plugin system and built-in plugins
│   ├── ui/             # PySide6 GUI
│   │   ├── models/     # Qt model/view models
│   │   ├── views/      # Main windows
│   │   └── widgets/    # Custom widgets
│   └── cli/            # Command-line interface
├── tests/
│   ├── unit/           # Unit tests
│   ├── integration/    # Integration tests with mocking
│   └── gui/            # GUI tests
└── docs/               # Documentation
```

## License

MIT License - see LICENSE file for details.

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Run tests and linting
5. Submit a pull request

## Support

- Issues: https://github.com/diskforge/diskforge/issues
- Documentation: https://diskforge.dev/docs
