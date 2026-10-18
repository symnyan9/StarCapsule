"""CLI for entirely local preparation, validation, packing and report building."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from . import __version__

from .schema import load_document


def _save(path, value, force=False):
    path = Path(path).resolve()
    if path.exists() and not force:
        raise ValueError(f"output exists: {path}; choose a new path or use --force")
    path.parent.mkdir(parents=True, exist_ok=True)
    # Write to a sibling first; parsing errors never truncate an existing output.
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    temporary.replace(path)
    return path


def parser():
    cli = argparse.ArgumentParser(prog="starcapsule", description="Offline CFD review HTML. STAR reads .sim; Python packs explicit exported data.")
    cli.add_argument("--version", action="version", version=f"StarCapsule Studio {__version__}")
    commands = cli.add_subparsers(dest="command", required=True)
    commands.add_parser("gui", help="open the native local SIM-to-HTML export interface")
    templates = commands.add_parser("templates", help="copy editable built-in HTML template packs")
    templates.add_argument("--output", "-o", required=True, help="new/empty template directory")
    template_check = commands.add_parser("validate-template", help="validate a local HTML/CSS template pack")
    template_check.add_argument("path")
    demo = commands.add_parser("demo", help="build a two-case synthetic offline HTML demonstration")
    demo.add_argument("--output", "-o", required=True, help="destination HTML file")
    demo.add_argument("--force", action="store_true")
    demo.add_argument("--template", help="local template-pack folder; default uses the built-in workbench")
    demo.add_argument("--language", choices=("en", "zh-CN"), help="report UI language; default English")
    build = commands.add_parser("build", help="build offline HTML from validated case/project JSON")
    build.add_argument("inputs", nargs="+", help="one project JSON or one/more case JSON files")
    build.add_argument("--output", "-o", required=True)
    build.add_argument("--title", default="StarCapsule Studio")
    build.add_argument("--force", action="store_true")
    build.add_argument("--template", help="local template-pack folder")
    build.add_argument("--language", choices=("en", "zh-CN"), help="report UI language; otherwise keep saved choice")
    upgrade = commands.add_parser("upgrade", help="update an exported HTML with current viewer assets; no STAR run")
    upgrade.add_argument("input", help="saved StarCapsule Studio HTML with embedded project data")
    upgrade.add_argument("--output", "-o", required=True, help="new HTML filename; source is preserved by default")
    upgrade.add_argument("--template", help="local template-pack folder; otherwise use the current built-in layout")
    upgrade.add_argument("--language", choices=("en", "zh-CN"), help="report UI language; otherwise keep saved choice")
    upgrade.add_argument("--force", action="store_true", help="explicitly replace an existing output")
    validate = commands.add_parser("validate", help="strictly validate case/project JSON")
    validate.add_argument("inputs", nargs="+")
    pack = commands.add_parser("pack", help="match CSV fields to native STL topology using an explicit JSON config")
    pack.add_argument("config")
    pack.add_argument("--output", "-o", required=True)
    pack.add_argument("--force", action="store_true")
    doctor = commands.add_parser("doctor", help="find local STAR/JDK without starting STAR or checking licenses")
    doctor.add_argument("--star", help="path to local starccm+ executable")
    inspect = commands.add_parser("inspect", help="prepare, optionally compile/run, a read-only STAR inventory macro")
    inspect.add_argument("sim", help="saved local .sim; opened only with --run")
    export = commands.add_parser("export", help="prepare, optionally compile/run, native surface/section export")
    export.add_argument("config", help="cfd-review-star-config JSON with explicit names/fields/reference metadata")
    for sub in (inspect, export):
        sub.add_argument("--output", "-o", required=True, help="new/empty export directory")
        sub.add_argument("--star", help="path to local starccm+ executable")
        sub.add_argument("--np", type=int, default=1, help="owned export process ranks (default: 1)")
        sub.add_argument("--timeout", type=int, default=1800, help="owned process timeout in seconds")
        sub.add_argument("--compile", action="store_true", dest="compile_api", help="compile macro against local STAR libraries")
        sub.add_argument("--run", action="store_true", help="actually start owned STAR read/export session; otherwise prepare only")
    return cli


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command == "gui":
            from .gui import main as gui_main
            return gui_main()
        elif args.command == "templates":
            from .templates import export_builtin_templates
            print(json.dumps(export_builtin_templates(args.output), ensure_ascii=False, default=str))
        elif args.command == "validate-template":
            from .templates import validate_template
            result = validate_template(args.path)
            print(f"VALID template: {result['name']}")
        elif args.command == "demo":
            from .demo import make_demo_project
            from .report import build_report
            print(build_report(make_demo_project(), args.output, overwrite=args.force, template=args.template, language=args.language))
        elif args.command == "build":
            from .report import build_report, project_from_cases
            docs = [load_document(path) for path in args.inputs]
            if len(docs) == 1 and docs[0]["schema"] == "cfd-review-project":
                project = docs[0]
            elif all(doc["schema"] == "cfd-review-case" for doc in docs):
                project = project_from_cases(docs, args.title)
            else:
                raise ValueError("build accepts one project or one/more cases; projects are not silently merged")
            print(build_report(project, args.output, overwrite=args.force, template=args.template, language=args.language))
        elif args.command == "validate":
            for path in args.inputs:
                doc = load_document(path)
                print(f"VALID {doc['schema']} v{doc['version']}: {Path(path).resolve()}")
        elif args.command == "upgrade":
            from .report import upgrade_report
            print(upgrade_report(args.input, args.output, overwrite=args.force, template=args.template, language=args.language))
        elif args.command == "pack":
            from .mesh_io import pack_case
            print(_save(args.output, pack_case(args.config), args.force))
        elif args.command == "doctor":
            from .star import doctor
            print(json.dumps(doctor(args.star), ensure_ascii=False, indent=2))
        elif args.command in ("inspect", "export"):
            from .star import inspect_sim, export_sim
            function = inspect_sim if args.command == "inspect" else export_sim
            source = args.sim if args.command == "inspect" else args.config
            result = function(source, args.output, args.star, args.np, args.timeout, args.run, args.compile_api)
            print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, json.JSONDecodeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
