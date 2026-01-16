# DiskForge Limitations

This document describes the limitations of DiskForge and the approaches used to work around them safely.

## General Limitations

### Administrator/Root Privileges Required

Most disk operations require elevated privileges:
- **Linux**: Run as root or with sudo
- **Windows**: Run as Administrator

The application will detect and warn when running without sufficient privileges.

### No Direct Hardware Access

DiskForge uses operating system tools and APIs rather than direct hardware access:
- **Advantage**: Better compatibility and safety
- **Limitation**: Cannot bypass OS-level protections or access raw hardware features

## Linux-Specific Limitations

### Tool Dependencies

DiskForge relies on standard Linux tools being installed:

| Operation | Required Tools |
|-----------|----------------|
| Inventory | `lsblk`, `blkid` |
| Partitioning | `sfdisk` or `parted` |
| Formatting | `mkfs.*` tools |
| Cloning | `dd` |
| Compression | `gzip`, `lz4`, or `zstd` |
| Resizing | `resize2fs`, `xfs_growfs`, `btrfs` |
| SMART | `smartctl` (optional) |
| Rescue ISO | `xorriso` (optional) |

If a tool is missing, the corresponding feature will be unavailable.

### Filesystem Support

Supported filesystems depend on installed `mkfs.*` tools:
- ext2/ext3/ext4: `e2fsprogs`
- XFS: `xfsprogs`
- Btrfs: `btrfs-progs`
- NTFS: `ntfs-3g`
- FAT32/exFAT: `dosfstools`, `exfatprogs`

### LVM and Software RAID

- **LVM**: Basic detection supported, but volume group operations require `lvm2` tools
- **mdadm RAID**: Detected as individual arrays, full management not implemented
- **Workaround**: Use native `lvm` and `mdadm` commands for advanced operations

### Encrypted Volumes (LUKS)

- LUKS volumes are detected but shown as "RAW" filesystem
- Encryption/decryption operations not implemented
- **Workaround**: Use `cryptsetup` to manage encryption, then use DiskForge on unlocked volumes

### ZFS Support

- ZFS pools are not supported (different architecture from traditional partitions)
- **Workaround**: Use ZFS native tools (`zpool`, `zfs`)

### Rescue ISO Creation

- Full bootable ISO creation requires `xorriso` and a Linux environment
- Without `xorriso`, creates a tar archive with rescue scripts instead
- ISO does not include a full Linux system - it's designed to be used from a live environment

## Windows-Specific Limitations

### PowerShell Dependency

- Requires PowerShell 5.0+ (included in Windows 10/11)
- Some operations fall back to `diskpart` if PowerShell cmdlets fail

### Dynamic Disks

- Basic support for viewing dynamic disk configurations
- Full management of dynamic disks not implemented
- **Workaround**: Use Disk Management MMC for dynamic disk operations

### BitLocker

- BitLocker-encrypted volumes detected but not manageable
- Cannot unlock, lock, or manage BitLocker encryption
- **Workaround**: Use `manage-bde` command or BitLocker settings

### Storage Spaces

- Storage Spaces pools detected as virtual disks
- Pool management not implemented
- **Workaround**: Use Storage Spaces settings or PowerShell

### ReFS Filesystem

- Can read ReFS volume information
- Cannot create or format ReFS (requires Windows Server)

### WinRE Integration

- Creates rescue scripts, not a full WinRE integration
- Manual steps required to integrate with Windows Recovery Environment
- Full instructions provided in generated README

### USB Devices

- May require unmounting/ejecting before operations
- Some USB devices have write-protection that can't be overridden programmatically

## Cloning Limitations

### Source Larger Than Target

- Cannot clone to a smaller target device
- **Workaround**: Shrink partitions before cloning, or use partition-level cloning

### Active Partitions

- Cannot clone mounted/active partitions reliably
- Always unmount source and target before cloning
- System partitions require booting from external media

### Sector Size Mismatch

- 4Kn drives with 4096-byte sectors may have compatibility issues with 512e drives
- Cloning between different sector sizes not recommended

## Imaging Limitations

### Image Format

- Uses raw block-level images with optional compression
- Not compatible with proprietary image formats (Ghost, Acronis, etc.)
- No incremental/differential backup support

### Compression

- Available algorithms depend on installed tools:
  - `gzip`: Widely available, slower
  - `lz4`: Fast, requires `lz4` tool
  - `zstd`: Best balance, requires `zstd` tool
- Windows has limited compression tool availability

### Large Images

- No built-in splitting for large images
- Image size limited by destination filesystem (e.g., FAT32 4GB limit)
- **Workaround**: Use NTFS or ext4 for large images

## Performance Considerations

### Block Size

- Default 64MB block size optimized for SSDs/NVMe
- May not be optimal for HDDs or network storage
- Not configurable without code changes

### Memory Usage

- Large block sizes require corresponding memory
- Compression adds memory overhead
- Consider available RAM when imaging large disks

### Network Operations

- No native network/NFS/SMB support for remote operations
- **Workaround**: Mount network shares locally first

## Safety Limitations

### SMART Data

- SMART availability depends on drive and controller support
- USB-attached drives often don't report SMART data
- NVMe SMART requires compatible `smartctl` version

### Power Loss Protection

- No built-in UPS integration
- Preflight check warns about battery status
- Operations can be interrupted by power loss

### Data Verification

- Verification compares source and target after write
- Does not detect degradation over time
- Not a substitute for regular backups

## GUI Limitations

### Display Requirements

- Requires X11/Wayland on Linux
- CLI available for headless systems
- Remote GUI requires X forwarding or VNC

### Refresh Rate

- Auto-refresh interval is 5 seconds minimum
- Hot-plug detection may have delays
- Manual refresh recommended after physical changes

## Planned Improvements

The following limitations may be addressed in future versions:

1. LVM volume group management
2. LUKS encryption support
3. ZFS pool detection
4. Incremental backup support
5. Network storage integration
6. Custom block size configuration
7. More image format support

## Reporting Issues

If you encounter a limitation not documented here, please report it:
- GitHub Issues: https://github.com/diskforge/diskforge/issues
- Include: OS version, disk types, error messages, and steps to reproduce
