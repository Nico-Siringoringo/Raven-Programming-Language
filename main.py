import os, sys

if getattr(sys, 'frozen', False):
    sys.path.insert(0, sys._MEIPASS)
else:
    src_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'src')
    if os.path.exists(src_dir):
        sys.path.insert(0, src_dir)

import time
import json
import subprocess
from argparse import ArgumentParser, Namespace, RawDescriptionHelpFormatter
from ctypes import CFUNCTYPE, c_int

from llvmlite import ir
import llvmlite.binding as llvm

def __import_compiler():
    from Lexer import Lexer
    from Parser import Parser
    from Compiler import Compiler
    return Lexer, Parser, Compiler

def build_arg_parser() -> ArgumentParser:
    parser = ArgumentParser(
        prog="Raven",
        description=__doc__,
        formatter_class=RawDescriptionHelpFormatter
    )
    parser.add_argument("--version", "-v", action="version", version="Raven 0.3.0-alpha")

    subparsers = parser.add_subparsers(dest="command", required=True)

    # run
    run_p = subparsers.add_parser("run", help="JIT compile and run a .rvn file")
    run_p.add_argument("file_path")
    run_p.add_argument("--debug", action="store_true", help="Dump AST and IR to debug/")
    run_p.add_argument("--opt", choices=["0", "1", "2", "3"], default="2", help="Optimization level (default: 2)")

    # build
    build_p = subparsers.add_parser("build", help="AOT compile to binary / IR / ASM / OBJ")
    build_p.add_argument("file_path")
    build_p.add_argument("-o", "--output", default=None)
    build_p.add_argument(
        "--emit", choices=["bin","obj","ir","asm"], default="bin",
        help="bin=native binary (default), obj, ir, asm",
    )
    build_p.add_argument("--opt", choices=["0","1","2","3"], default="2")
    build_p.add_argument("--debug", action="store_true")

    # check
    check_p = subparsers.add_parser("check", help="Parse and type-check a file without compiling")
    check_p.add_argument("file_path")

    return parser

# region Core pipeline helpers
def __die(msg: str) -> None:
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)

def __write_debug(filename: str, content: str) -> None:
    os.makedirs("debug", exist_ok=True)
    path = os.path.join("debug", filename)
    with open(path, "w") as f:
        f.write(content)
    print(f"[debug] wrote {path}")

def __ensure_ext(path: str, ext: str) -> str:
    return path if path.endswith(ext) else  path + ext

def __find_linker() -> str:
    for linker in ("gcc", "clang", "cc"):
        if subprocess.run(["which", linker], capture_output=True).returncode == 0:
            return linker
        __die("no system linker found — install gcc or clang")
# endregion

def compile_source(file_path: str, debug: bool = False) -> ir.Module:
    Lexer, Parser, Compiler = __import_compiler()

    if not os.path.exists(file_path):
        __die(f"File not found: '{file_path}'")

    with open(file_path, "r") as f:
        code = f.read()

    p = Parser(Lexer(source=code))
    program = p.parse_program()

    if p.errors:
        print("error: parse failed\n", file=sys.stderr)
        for err in p.errors:
            print(f"  {err}", file=sys.stderr)
        sys.exit(1)

    if debug:
        __write_debug("ast.json", json.dumps(program.json(), indent=4))

    c = Compiler(source_file=file_path)
    c.compile(node=program)

    if c.errors:
        print("error: compilation failed\n", file=sys.stderr)
        for err in c.errors:
            print(f"  {err}", file=sys.stderr)
        sys.exit(1)

    module: ir.Module = c.module
    module.triple = llvm.get_default_triple()

    if debug:
        __write_debug("ir.ll", str(module))

    return module

def optimise(mod_ref: llvm.ModuleRef, opt_level: int) -> None:
    tm = llvm.Target.from_default_triple().create_target_machine(opt=opt_level)
    pto = llvm.create_pipeline_tuning_options(speed_level=opt_level)
    pb = llvm.create_pass_builder(tm, pto)
    npm = pb.getModulePassManager()
    npm.run(mod_ref, pb)

def parse_optimise(module: ir.Module, opt_level: int = 2) -> llvm.ModuleRef:
    llvm.initialize_native_target()
    llvm.initialize_all_asmprinters()

    try:
        mod_ref = llvm.parse_assembly(str(module))
        mod_ref.verify()
    except Exception as e:
        __die(f"LLVM error: {e}")

    if opt_level > 0:
        optimise(mod_ref, opt_level)

    return mod_ref

def make_target_machine(opt_level: int = 2, reloc: str = "default") -> llvm.TargetMachine:
    return (
        llvm.Target.from_default_triple().create_target_machine(reloc=reloc, codemodel="default", opt=opt_level)
    )

# region Commands
def cmd_check(args: Namespace) -> None:
    compile_source(args.file_path)
    print(f"{args.file_path} — no errors")

def cmd_run(args: Namespace) -> None:
    opt = int(args.opt)
    module = compile_source(args.file_path, debug=args.debug)
    mod_ref = parse_optimise(module, opt)

    jit = llvm.create_lljit_compiler()
    rt = (
        llvm.JITLibraryBuilder()
        .add_current_process()
        .export_symbol("main")
        .add_ir(mod_ref)
        .link(jit, "program")
    )

    cfunc = CFUNCTYPE(c_int)(rt["main"])

    t0 = time.perf_counter()
    result = cfunc()
    elapsed = (time.perf_counter() - t0) * 1000

    print(f"\nProgram exited: {result} ({elapsed:.3f} ms)")

def cmd_build(args: Namespace) -> None:
    opt = int(args.opt)
    emit = args.emit
    stem = os.path.splitext(os.path.basename(args.file_path))[0]
    out = args.output or stem

    module = compile_source(args.file_path, debug=args.debug)

    if emit == "ir":
        path = __ensure_ext(out, ".ll")
        with open(path, "w") as f:
            f.write(str(module))
        print(f"Wrote IR ➔ {path}")
        return
    
    mod_ref = parse_optimise(module, opt)
    tm = make_target_machine(opt, reloc="pic")

    if emit == "asm":
        path = __ensure_ext(out, ".s")
        with open(path, "w") as f:
            f.write(tm.emit_assembly(mod_ref))
        print(f"Wrote ASM ➔ {path}")
        return

    obj_bytes = tm.emit_object(mod_ref)

    if emit == "obj":
        path = __ensure_ext(out, ".o")
        with open(path, "w") as f:
            f.write(obj_bytes)
        print(f"Wrote OBJ ➔ {path}")
        return
    
    obj_path = out + ".o"
    with open(obj_path, "wb") as f:
        f.write(obj_bytes)

    linker = __find_linker()
    result = subprocess.run(
        [linker, obj_path, "-o", out, "-lm"],
        capture_output=True, text=True
    )
    os.remove(obj_path)

    if result.returncode != 0:
        print(f"error: linker failed\n{result.stderr}", file=sys.stderr)
        sys.exit(1)

    os.chmod(out, 0o755)
    print(f"Built    ➔ {out}")
# endregion

def entry_point():
    args = build_arg_parser().parse_args()
    match args.command:
        case "run": cmd_run(args)
        case "build": cmd_build(args)
        case "check": cmd_check(args)


if __name__ == "__main__":
    entry_point()