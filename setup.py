"""
Setup script for DiskForge (alternative to Poetry build).
"""

from __future__ import annotations

from pathlib import Path
import sys

from setuptools import find_packages, setup

ROOT = Path(__file__).resolve().parent
README = ROOT / "README.md"

long_description = ""
if README.exists():
    long_description = README.read_text(encoding="utf-8")

is_linux = sys.platform.startswith("linux")

if len(sys.argv) == 1:
    print("No command supplied; defaulting to `install`.")
    sys.argv.append("install")

setup(
    name="diskforge",
    version="1.0.0",
    description="Production-grade cross-platform disk management application",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="DiskForge Team",
    author_email="team@diskforge.dev",
    license="MIT",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    package_data={"diskforge": ["resources/*"]},
    python_requires=">=3.12",
    install_requires=[
        "PySide6>=6.6.0",
        "pydantic>=2.5.0",
        "structlog>=24.1.0",
        "click>=8.1.0",
        "rich>=13.7.0",
        "psutil>=5.9.0",
        "humanize>=4.9.0",
    ],
    extras_require={
        "dev": [
            "pytest>=8.0.0",
            "pytest-cov>=4.1.0",
            "pytest-mock>=3.12.0",
            "ruff>=0.2.0",
            "mypy>=1.8.0",
        ],
    },
    entry_points={
        "console_scripts": [
            "diskforge=diskforge.cli.main:main",
        ],
        "gui_scripts": [
            "DiskForge=diskforge.ui.main:main",
            "diskforge-gui=diskforge.ui.main:main",
        ],
    },
    data_files=(
        [
            ("share/applications", ["src/diskforge/resources/diskforge.desktop"]),
            (
                "share/icons/hicolor/scalable/apps",
                ["src/diskforge/resources/diskforge.svg"],
            ),
        ]
        if is_linux
        else []
    ),
    classifiers=[
        "Development Status :: 4 - Beta",
        "Environment :: Console",
        "Environment :: X11 Applications :: Qt",
        "Intended Audience :: System Administrators",
        "Operating System :: Microsoft :: Windows :: Windows 11",
        "Operating System :: POSIX :: Linux",
        "Programming Language :: Python :: 3.12",
        "Topic :: System :: Systems Administration",
    ],
)
