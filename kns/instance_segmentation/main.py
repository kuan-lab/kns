#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Instance segmentation module — supports both direct CLI execution and unified package CLI interface.

Provides:
- main(): standalone CLI for segmentation/merge/tools pipeline
- run(args, global_cfg): for external CLI calls
- run_interactive(): for interactive (menu-style) usage
"""

import argparse
import logging
import shutil
import os
import time
import yaml
import signal
import threading
import inspect

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.prompt import Prompt
from rich import box
import torch

console = Console()

from kns.instance_segmentation.config import (
    load_config,
    get_stage_config,
    load_global_config_path,
)

# === Pipeline modules ===
from kns.instance_segmentation.stages.segmentation_stage import (
    segmentation_blocks,
    segmentation_blocks_parallel,
)
from kns.instance_segmentation.stages.segmentation_stage_hpc import segmentation_blocks_hpc
from kns.instance_segmentation.stages.merge_pools import build_id_pools_parallel
from kns.instance_segmentation.stages.merge_apply import apply_pools_to_global
from kns.instance_segmentation.state.checkpoint import load_merge_state

# === Tools ===
from kns.instance_segmentation.tools.convert_prec import convert_prec
from kns.instance_segmentation.tools.convert_prec_hpc import convert_prec_hpc
from kns.instance_segmentation.tools.downsample_prec import downsample_prec
from kns.instance_segmentation.tools.downsample_prec_hpc import downsample_prec_hpc
from kns.instance_segmentation.tools.gen_mask import gen_aff_mask
from kns.instance_segmentation.tools.gen_mask_hpc import gen_aff_mask_hpc
from kns.instance_segmentation.tools.mask_prec import mask_prec
from kns.instance_segmentation.tools.mask_prec_hpc import mask_prec_hpc
from kns.instance_segmentation.tools.mask_tif import mask_tif
from kns.instance_segmentation.tools.mask_tif_hpc import mask_tif_hpc
from kns.instance_segmentation.tools.resize_tif import resize_tif
from kns.instance_segmentation.tools.resize_tif_hpc import resize_tif_hpc

from kns.instance_segmentation.utils.interrupts import InterruptController

# ==========================================================
# Unified CLI interface (for package-level use)
# ==========================================================
def edit_stage_config(config_path: str, stage_name: str):
    """Ask user whether to modify stage-specific YAML config before running."""
    print(f"\nStage: {stage_name}")
    print(f"Config path: {config_path}")

    if not os.path.exists(config_path):
        print(f"Config file not found at {config_path}, skipping modification.")
        return config_path
            
    if not Prompt.ask("[white]> Modify this stage config before running? (y/n)[/white]", default="n").lower().startswith("y"):
        return config_path

    # Read configuration file
    with open(config_path, "r") as f:
        cfg_data = yaml.safe_load(f)

    # Display Configuration Items (Single Layer)
    flat_keys = []
    flat_sections = []
    print("\nAvailable parameters in config:")
    config_table = Table(
            box=box.SIMPLE,
            title_style="bold bright_white",
            header_style="bright_white",
            show_header=True
        )
    config_table.add_column("Index", justify="center", style="white")
    config_table.add_column("Section", style="white")
    config_table.add_column("Parameter", style="white")
    config_table.add_column("Value", style="white")

    i = 1

    for section, sub in cfg_data.items():
        # console.print(f"[bold]{section}[/bold]:")
        
        if isinstance(sub, dict):
            for k, v in sub.items():
                # console.print(f"   - {k}: [cyan]{v}[/cyan]")
                flat_keys.append(k)
                flat_sections.append(section)
                config_table.add_row(f"{i}", f"{section}", f"{k}", f"[cyan]{v}[/cyan]")
                i += 1
        else:
            # console.print(f"   - [cyan]{sub}[/cyan]")
            flat_keys.append(section)
            flat_sections.append(section)
            config_table.add_row(f"{i}", f"{section}", f"{section}",  f"[cyan]{sub}[/cyan]")
            i += 1
        
    console.print(config_table)

    # idx = 1
    # for k, v in cfg_data.items():
    #     print(f"{idx}. {k}: {v}")
    #     flat_keys.append(k)
    #     idx += 1

    while True:
        choice = input("> Select parameter to modify (number, or ENTER to finish): ").strip()
        if choice == "":
            break
        if not choice.isdigit() or not (1 <= int(choice) <= len(flat_keys)):
            print("Invalid selection.")
            continue

        key = flat_keys[int(choice) - 1]
        section_key = flat_sections[int(choice) - 1]
        if key == section_key:
            old_val = cfg_data[section_key]
            print(f"Current value for {section_key}/{key}: {old_val}")
            new_val = input("New value: ").strip()
            if new_val == "":
                print("No change made.")
                continue

            # Automatic Type Conversion (int/float)
            try:
                if "." in new_val:
                    new_val = float(new_val)
                else:
                    new_val = int(new_val)
            except ValueError:
                pass

            cfg_data[section_key] = new_val
        else:
            old_val = cfg_data[section_key][key]
            print(f"Current value for {section_key}/{key}: {old_val}")
            new_val = input("New value: ").strip()
            if new_val == "":
                print("No change made.")
                continue

            # Automatic Type Conversion (int/float)
            try:
                if "." in new_val:
                    new_val = float(new_val)
                else:
                    new_val = int(new_val)
            except ValueError:
                pass

            cfg_data[section_key][key] = new_val
        print(f"Updated {key} → {new_val}")

    # Save to temporary file
    temp_path = config_path + ".tmp"
    with open(temp_path, "w") as f:
        yaml.safe_dump(cfg_data, f, sort_keys=False)
    print(f"Temporary modified config saved: {temp_path}")

    return temp_path


# ------------------------------------------
# Main
# ------------------------------------------
def run(args, global_cfg):
    """
    Unified CLI-compatible entrypoint with per-stage config editing and interrupt handling.
    Supports safe interruption across multithreaded tasks.
    """
    logging.basicConfig(
        level=logging.DEBUG if getattr(args, "debug", False) else logging.INFO,
        format="[%(levelname)s] %(message)s",
    )

    # Resolve config paths
    seg_cfg_path = (
        global_cfg.get("instance_segmentation", {})
        .get("main", "kns/instance_segmentation/configs/config.yaml")
    )
    prec_cfg_path = (
        global_cfg.get("instance_segmentation", {})
        .get("prec", "kns/instance_segmentation/configs/config_prec.yaml")
    )
    downsample_cfg_path = (
        global_cfg.get("instance_segmentation", {})
        .get("downsample", "kns/instance_segmentation/configs/config_downsample.yaml")
    )
    gen_mask_cfg_path = (
        global_cfg.get("instance_segmentation", {})
        .get("gen_mask", "kns/instance_segmentation/configs/config_gen_mask.yaml")
    )
    mask_prec_cfg_path = (
        global_cfg.get("instance_segmentation", {})
        .get("mask_prec", "kns/instance_segmentation/configs/config_mask.yaml")
    )
    mask_tif_cfg_path = (
        global_cfg.get("instance_segmentation", {})
        .get("mask_tif", "kns/instance_segmentation/configs/config_mask_tif.yaml")
    )
    resize_tif_cfg_path = (
        global_cfg.get("instance_segmentation", {})
        .get("resize_tif", "kns/instance_segmentation/configs/config_resize_tif.yaml")
    )

    def confirm_stage(stage_name):
        print(f"\nStarting stage: {stage_name}")
        print("Press Enter to continue or type 'q' to cancel.")
        resp = input("> ").strip().lower()
        if resp == "q":
            # print(f"Canceled stage: {stage_name}")
            console.print(f"[bold red]▶ Canceled stage: {stage_name}.[/bold red]\n")
            return False
        return True

    # -----------------------------------
    # Stage logic
    # -----------------------------------
    try:
        if args.stage == "segmentation":
            if not confirm_stage("Segmentation"):
                return
            cfg_path = edit_stage_config(seg_cfg_path, "Segmentation Stage")
            cfg = load_config(cfg_path)
            stage_cfg = get_stage_config(cfg, "segmentation")
            func = segmentation_blocks_parallel if stage_cfg.get("parallel", False) else segmentation_blocks
            with InterruptController():
                func(cfg, stage_cfg, restart=args.restart)
            print("Press Enter to return menu.")
            input("> ").strip().lower()
            # safe_run(func, cfg, stage_cfg, restart=args.restart)

        elif args.stage == "segmentation-hpc":
            if not confirm_stage("Segmentation-HPC"):
                return
            cfg_path = edit_stage_config(seg_cfg_path, "Segmentation-HPC Stage")
            cfg = load_config(cfg_path)
            stage_cfg = get_stage_config(cfg, "segmentation")
            with InterruptController():
                segmentation_blocks_hpc(cfg, stage_cfg, restart=args.restart, dry_run=False)
            print("Press Enter to return menu.")
            input("> ").strip().lower()
            # safe_run(segmentation_blocks_hpc, cfg, stage_cfg, restart=args.restart, dry_run=False)

        elif args.stage == "merge-pools":
            if not confirm_stage("Merge-Pools"):
                return
            cfg_path = edit_stage_config(seg_cfg_path, "Merge-Pools Stage")
            cfg = load_config(cfg_path)
            stage_cfg = get_stage_config(cfg, "merge")
            with InterruptController():
                build_id_pools_parallel(cfg, stage_cfg, restart=args.restart)
            print("Press Enter to return menu.")
            input("> ").strip().lower()
            # safe_run(build_id_pools_parallel, cfg, stage_cfg, restart=args.restart)

        elif args.stage == "merge-apply":
            if not confirm_stage("Merge-Apply"):
                return
            cfg_path = edit_stage_config(seg_cfg_path, "Merge-Apply Stage")
            cfg = load_config(cfg_path)
            stage_cfg = get_stage_config(cfg, "merge")
            with InterruptController():
                apply_pools_to_global(cfg, stage_cfg)
            print("Press Enter to return menu.")
            input("> ").strip().lower()
            # safe_run(apply_pools_to_global, cfg, stage_cfg)

        elif args.stage == "tools":
            if not confirm_stage(f"Tool: {args.tools}"):
                return
            tool_map = {
                "convert-prec": prec_cfg_path,
                "convert-prec-hpc": prec_cfg_path,
                "downsample-prec": downsample_cfg_path,
                "downsample-prec-hpc": downsample_cfg_path,
                "generate-mask": gen_mask_cfg_path,
                "generate-mask-hpc": gen_mask_cfg_path,
                "mask-prec": mask_prec_cfg_path,
                "mask-prec-hpc": mask_prec_cfg_path,
                "mask-tif": mask_tif_cfg_path,
                "mask-tif-hpc": mask_tif_cfg_path,
                "resize-tif": resize_tif_cfg_path,
                "resize-tif-hpc": resize_tif_cfg_path,
            }
            tool_cfg_path = tool_map.get(args.tools.lower(), prec_cfg_path)
            # print(args.tools)
            tool_cfg_path = edit_stage_config(tool_cfg_path, f"Tool: {args.tools}")
            print(f"Running tool with config: {tool_cfg_path}")
            tool_cfg = load_config(tool_cfg_path)
            with InterruptController():
                handle_tools(args, tool_cfg)
                # handle_tools(args, global_cfg)
            print("Press Enter to return menu.")
            input("> ").strip().lower()
            # safe_run(handle_tools, args, global_cfg)

        elif args.stage == "status":
            cfg = load_config(seg_cfg_path)
            folder_done = cfg["checkpoint"]["segmentation_dir"]
            print(f"[Checkpoint folder]: {folder_done}")
            if not os.path.exists(folder_done):
                print("Segmentation state: checkpoint folder not found.")
            else:
                files = os.listdir(folder_done)
                if not files:
                    print("Segmentation state: no block done.")
                else:
                    print("Segmentation state:")
                    for f in files:
                        print(f"[Done] {f}")
            print("Press Enter to return menu.")
            input("> ").strip().lower()
                        
        elif args.stage == "clean":
            if not confirm_stage("Clean Temporary Files"):
                return
            cfg = load_config(seg_cfg_path)
            for path in [
                cfg["checkpoint"]["segmentation_dir"],
                cfg["checkpoint"]["merge_dir"],
                cfg["segmentation_stage"]["metadata_dir"],
            ]:
                if os.path.exists(path):
                    shutil.rmtree(path)
                    print(f"[INFO] Cleaned: {path}")
                else:
                    print(f"[INFO] Cleaned: {path}")
            print("Press Enter to return menu.")
            input("> ").strip().lower()
        
        # return True
        # if stop_flag.is_set():
        #     print("Stage ended early due to interruption.")
        # else:
        console.print(f"[bold green]▶ Stage {args.stage} completed.[/bold green]\n")

    except KeyboardInterrupt:
        print("\nExecution interrupted abruptly by user.")
    finally:
        logging.shutdown()

# ==========================================================
# Tool dispatcher
# ==========================================================
def handle_tools(args, tool_cfg):
    """Dispatch preprocessing tools."""

    tools_map = {
        "convert-prec": lambda: convert_prec(tool_cfg),
        "convert-prec-hpc": lambda: convert_prec_hpc(tool_cfg),
        "downsample-prec": lambda: downsample_prec(tool_cfg),
        "downsample-prec-hpc": lambda: downsample_prec_hpc(tool_cfg),
        "generate-mask": lambda: gen_aff_mask(tool_cfg),
        "generate-mask-hpc": lambda: gen_aff_mask_hpc(tool_cfg),
        "mask-prec": lambda: mask_prec(tool_cfg),
        "mask-prec-hpc": lambda: mask_prec_hpc(tool_cfg),
        "mask-tif": lambda: mask_tif(tool_cfg),
        "mask-tif-hpc": lambda: mask_tif_hpc(tool_cfg),
        "resize-tif": lambda: resize_tif(tool_cfg),
        "resize-tif-hpc": lambda: resize_tif_hpc(tool_cfg),
    }

    tool_fn = tools_map.get(args.tools.lower())
    if tool_fn is None:
        print(f"Unknown tool: {args.tools}")
    else:
        with InterruptController():
            tool_fn()


# ==========================================================
# Interactive CLI mode
# ==========================================================
def load_global_config(path="kns/config.yaml"):
    """Load YAML config file."""
    try:
        with open(path, "r") as f:
            cfg = yaml.safe_load(f)
        print(f"\nLoaded global config from: {path}")
        return cfg, path
    except FileNotFoundError:
        print(f"\nGlobal config not found at {path}. Using defaults.")
        return {}, path


def save_global_config(cfg, path):
    """Save updated YAML config."""
    with open(path, "w") as f:
        yaml.safe_dump(cfg, f, sort_keys=False)
    print(f"Saved updated global config to: {path}")


def modify_global_config(cfg, cfg_path):
    """Interactive menu to modify config path or values."""
    print("\nModify Global Config")

    new_path = input(f"> Enter new config file path (blank to keep {cfg_path}): ").strip()
    if new_path:
        cfg, cfg_path = load_global_config(new_path)

    flat_items = []
    # print("\nAvailable config parameters:")
    idx = 1
    # for section, sub in cfg.items():
    #     if isinstance(sub, dict):
    #         for k, v in sub.items():
    #             flat_items.append((f"{section}/{k}", v))
    #             print(f"{idx}. {section}/{k}: {v}")
    #             idx += 1
    #     else:
    #         flat_items.append((section, sub))
    #         print(f"{idx}. {section}: {sub}")
    #         idx += 1
    console.rule("[bold bright_white]Available Config Parameters[/bold bright_white]", style="bright_cyan")
    config_table = Table(
            box=box.SIMPLE,
            title_style="bold bright_white",
            header_style="bright_white",
            show_header=True
        )
    config_table.add_column("Index", justify="center", style="white")
    config_table.add_column("Section", style="white")
    config_table.add_column("Parameter", style="white")
    config_table.add_column("Value", style="white")

    for section, sub in cfg.items():
        # console.print(f"[bold]{section}[/bold]:")
        if isinstance(sub, dict):
            for k, v in sub.items():
                # console.print(f"   - {k}: [cyan]{v}[/cyan]")
                flat_items.append((f"{section}/{k}", v))
                config_table.add_row(f"{idx}", f"{section}", f"{k}", f"[cyan]{v}[/cyan]")
                idx += 1
        else:
            # console.print(f"   - [cyan]{sub}[/cyan]")
            flat_items.append((section, sub))
            config_table.add_row("-", "-", "-", f"[cyan]{sub}[/cyan]")
            idx += 1
        
    console.print(config_table)
    while True:
        choice = input("> Select parameter to modify (number, or ENTER to finish): ").strip()
        if choice == "":
            break
        if not choice.isdigit() or not (1 <= int(choice) <= len(flat_items)):
            print("Invalid selection.")
            continue

        key_path, old_val = flat_items[int(choice) - 1]
        # print('\n')
        print(f"Current value for {key_path}: {old_val}")
        new_val = input("> New value: ").strip()
        if new_val == "":
            print("No change made.")
            continue

        # Apply modification
        parts = key_path.split("/")
        target = cfg
        for p in parts[:-1]:
            target = target[p]
        target[parts[-1]] = new_val
        print(f"Updated {key_path} → {new_val}")

    if Prompt.ask("[white]> Save changes to file? (y/n)[/white]", default="n").lower().startswith("y"):
        save_global_config(cfg, cfg_path)
    else:
        print("Using in-memory config (not saved).")

    return cfg, cfg_path


def run_interactive():
    """Interactive CLI mode with styled Rich interface."""
    console.print("\n[bold bright_white] Instance Segmentation Interactive Mode[/bold bright_white]\n")

    cfg_path = "kns/config.yaml"
    cfg, cfg_path = load_global_config(cfg_path)

    # choice_pool = [str(i) for i in range(10)] + ["h", "help"]
    choice_pool = [str(i) for i in range(10)]

    # === Help descriptions ===
    help_descriptions = {
        "1": "Run segmentation locally. Processes image tiles and generates labeled segments.",
        "2": "Run segmentation on HPC (cluster mode). Uses SLURM or batch jobs.",
        "3": "Merge multiple segmentation pools into one unified result.",
        "4": "Apply merged results to generate final labeled volume.",
        "5": "Tools for data preparation and post-processing (convert, resize, masking, etc.).",
        "6": "Check current job or pipeline status (local/HPC).",
        "7": "Clean temporary files, logs, and cache data.",
        "8": "Edit global configuration interactively.",
        "9": "Display current global configuration values.",
        "0": "Exit the pipeline.",
    }

    # === Tool List ===
    tool_list = [
        "Convert-prec",
        "Convert-prec-hpc",
        "Downsample-prec",
        "Downsample-prec-hpc",
        "Generate-mask",
        "Generate-mask-hpc",
        "Mask-prec",
        "Mask-prec-hpc",
        "Mask-tif",
        "Mask-tif-hpc",
        "Resize-tif",
        "Resize-tif-hpc",
    ]

    tool_help = {
        "convert-prec": "Convert tif/h5 data to precomputed format.",
        "convert-prec-hpc": "Convert tif/h5 data to precomputed format by using hpc resources.",
        "downsample-prec": "Create lower-resolution mipmap levels using voxel downsampling for precomputed data.",
        "downsample-prec-hpc": "Create lower-resolution mipmap levels using voxel downsampling for precomputed data by using hpc resources.",
        "generate-mask": "Generate binary masks from affinity maps.",
        "generate-mask-hpc": "Generate binary masks from affinity maps by using hpc resources.",
        "mask-prec": "Apply a mask to prec images, preserving structure.",
        "mask-prec-hpc": "Apply a mask to prec images by using hpc resources.",
        "mask-tif": "Apply a mask to tif images, preserving structure.",
        "mask-tif-hpc": "Apply a mask to tif images by using hpc resources.",
        "resize-tif": "Resize tif volumes to new voxel size or dimension.",
        "resize-tif-hpc": "Resize tif volumes to new voxel size or dimension by using hpc resources.",
    }

    while True:
        console.rule("[bold bright_white]Instance Segmentation Menu[/bold bright_white]", style="bold white")

        table = Table(show_header=True, box=box.SIMPLE, border_style="white", 
                      title_style="bold bright_white",header_style="bright_white",)
        
        table.add_column("Option", justify="center", style="white")
        table.add_column("Function", style="white")
        table.add_column("Description", style="white")
        table.add_row("1", "Affinity Map Segmentation", "Run affinity map segmentation using local resources")
        table.add_row("2", "Affinity Map Segmentation HPC", "Run affinity map segmentation using HPC resources")
        table.add_row("3", "Merge Blocks [Pools]", "Generate a global ID pool for all segmentated blocks")
        table.add_row("4", "Merge Blocks [Apply]", "Apply the global ID pool to all segmentated blocks")
        table.add_row("5", "Tools", "Data preprocessing / postprocessing utilities")
        table.add_row("6", "Status", "View current segmentation status")
        table.add_row("7", "Clean", "Remove checkpoints and temp data of segmentation")
        table.add_row("8", "Modify global config", "Modify the global configuration files for each module")
        table.add_row("9", "View current config", "View the global configuration files for each module")
        table.add_row("0", "Return Main", "Return to main menu")
        # table.add_row("h", "Help", "Function description")

        console.print(table)

        choice = Prompt.ask("[bright_white]> Select stage[/bright_white]", default="0").strip().lower()
        if choice not in choice_pool:
            console.print("[red]Invalid selection. Try again.[/red]")
            continue

        # === Help screen ===
        # if choice in ["h", "help"]:
        #     console.rule("[magenta]Function Help[/magenta]", style="bright_magenta")
        #     for k in sorted(help_descriptions.keys(), key=int):
        #         console.print(f"[cyan]{k}.[/] {help_descriptions[k]}")
        #     console.print()
        #     continue

        if choice == "0":
            console.print("[yellow]Exit Instance Segmentation Pipeline.[/yellow]")
            break

        if choice == "8":
            cfg, cfg_path = modify_global_config(cfg, cfg_path)
            print("Press Enter to return menu.")
            input("> ").strip().lower()
            continue

        if choice == "9":
            console.rule("[bold bright_white]Current Global Config[/bold bright_white]", style="bright_cyan")
            config_table = Table(
                    box=box.SIMPLE,
                    title_style="bold bright_white",
                    header_style="bright_white",
                    show_header=True
                )
            config_table.add_column("Index", justify="center", style="white")
            config_table.add_column("Section", style="white")
            config_table.add_column("Parameter", style="white")
            config_table.add_column("Value", style="white")
    
            for section, sub in cfg.items():
                # console.print(f"[bold]{section}[/bold]:")
                i = 1
                if isinstance(sub, dict):
                    for k, v in sub.items():
                        # console.print(f"   - {k}: [cyan]{v}[/cyan]")
                        config_table.add_row(f"{i}", f"{section}", f"{k}", f"[cyan]{v}[/cyan]")
                        i += 1
                else:
                    # console.print(f"   - [cyan]{sub}[/cyan]")
                    config_table.add_row("-", "-", "-", f"[cyan]{sub}[/cyan]")
                    i += 1
                
            console.print(config_table)
            print("Press Enter to return menu.")
            input("> ").strip().lower()
            continue
        
        cfg, cfg_path = load_global_config(cfg_path)

        # === Stage argument setup ===
        class Args:
            pass

        args = Args()
        mapping = {
            "1": "segmentation",
            "2": "segmentation-hpc",
            "3": "merge-pools",
            "4": "merge-apply",
            "5": "tools",
            "6": "status",
            "7": "clean",
        }
        args.stage = mapping.get(choice)
        args.debug = False

        if args.stage in ["segmentation", "segmentation-hpc", "merge-pools"]:
            restart_choice = Prompt.ask("[white]> Restart? (y/n)[/white]", default="n").lower()
            args.restart = restart_choice.startswith("y")
        else:
            args.restart = False

        # === Tools submenu ===
        if args.stage == "tools":
            while True:
                console.rule("[bold bright_white]Tools Menu[/bold bright_white]", style="bold white")
                tool_table = Table(show_header=True, box=box.SIMPLE, border_style="white", 
                      title_style="bold bright_white",header_style="bright_white",)
                tool_table.add_column("Option", justify="center", style="white")
                tool_table.add_column("Tool", style="white")
                tool_table.add_column("Description", style="white")
                for i, name in enumerate(tool_list, start=1):
                    desc = tool_help.get(name.lower(), "No description available.")
                    # tool_table.add_row(f"[cyan]{i}.[/] {name}")
                    tool_table.add_row(f"{i}", f"{name}", f"{desc}")

                tool_table.add_row("0", f"Return", "Return to instance segmentation menu")
                # tool_table.add_row("h", f"Help", "Tools description")
                console.print(tool_table)

                selected = Prompt.ask("[bright_white]> Select tool [index][/bright_white]", default="0").strip().lower()
                if selected in ["0", ""]:
                    console.print("[yellow]Returning to main menu...[/yellow]")
                    break

                # === Tool help ===
                # if selected in ["h", "help"]:
                #     console.rule("[magenta]Tool Descriptions[/magenta]", style="bright_magenta")
                #     help_table = Table(show_header=True, box=box.SIMPLE, border_style="bright_white")
                #     help_table.add_column("Option", justify="center", style="white")
                #     help_table.add_column("Tool", style="white")
                #     help_table.add_column("Description", style="white")
                #     for i, name in enumerate(tool_list, start=1):
                #         desc = tool_help.get(name.lower(), "No description available.")
                #         help_table.add_row(f"{i}", f"{name}", f"{desc}")
                #     console.print(tool_table)
                #     continue

                selected_indices = []
                for x in selected.replace(",", " ").split():
                    if x.isdigit():
                        idx = int(x)
                        if 1 <= idx <= len(tool_list):
                            selected_indices.append(tool_list[idx - 1])
                    elif x in tool_list:
                        selected_indices.append(x)

                if not selected_indices:
                    console.print("[red]No valid tool selected.[/red]")
                    continue

                for tool in selected_indices:
                    console.print(f"\n[green]▶ Running tool:[/] [cyan]{tool}[/cyan]")
                    args.tools = tool
                    run(args, cfg)

                console.print("[bold green]Selected tool finished.[/bold green]")
                break

            continue

        console.print(f"\n[green]▶ Executing stage:[/] [cyan]{args.stage}[/cyan]")
        run(args, cfg)
        # console.print(f"[bold green] Stage completed.[/bold green]\n")


# ==========================================================
# main()
# ==========================================================
def main():
    t1 = time.time()
    parser = argparse.ArgumentParser(description="Block-wise segmentation pipeline")
    parser.add_argument(
        "--stage",
        choices=[
            "segmentation",
            "segmentation-hpc",
            "merge-pools",
            "merge-apply",
            "tools",
            "status",
            "clean",
        ],
        required=True,
    )
    parser.add_argument(
        "--tools",
        choices=[
            "convert-prec",
            "convert-prec-hpc",
            "downsample-prec",
            "downsample-prec-hpc",
            "generate-mask",
            "generate-mask-hpc",
            "mask-prec",
            "mask-prec-hpc",
            "mask-tif",
            "mask-tif-hpc",
            "resize-tif",
            "resize-tif-hpc",
        ],
        required=False,
    )
    parser.add_argument("--restart", action="store_true")
    parser.add_argument("--force-overlap", action="store_true")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    global_cfgs = load_global_config_path("kns/config.yaml")
    run(args, global_cfgs)
    t2 = time.time()
    print(f"Total runtime: {t2 - t1:.2f}s")


if __name__ == "__main__":
    main()
