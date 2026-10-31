"""Build the owned FPLS v4 queue trace and admission guard; never installs."""
from pathlib import Path
import shutil
import subprocess
import tempfile
from types import SimpleNamespace
from build_adapter import armasm, HERE


def build():
    with tempfile.TemporaryDirectory(prefix='producer-trace-') as tmp:
        assembly=Path(tmp)/'trace.S'
        subprocess.run([shutil.which('clang') or 'clang', '-target', 'armv7-none-eabi',
            '-marm', '-mfloat-abi=soft', '-mfpu=none', '-O2', '-ffreestanding',
            '-fno-builtin', '-fno-jump-tables', '-fno-addrsig', '-fno-vectorize',
            '-fno-slp-vectorize', '-fno-unwind-tables', '-fno-asynchronous-unwind-tables',
            '-Wall', '-Wextra', '-Werror', '-Wno-unused-command-line-argument',
            '-S', str(HERE/'producer_trace.c'),
            '-o', str(assembly)], check=True)
        assembly.write_text(assembly.read_text()+'\n'+(HERE/'producer_trace.S').read_text())
        _,_,sections=armasm._parse(armasm._compile(assembly))
        for name,(_,section) in sections.items():
            if section[2]&2 and section[5] and name not in ('.text','.ARM.exidx'):
                raise ValueError('unplaced producer section: '+name)
        code=armasm.assemble(assembly)
        symbols=armasm.symbols(assembly)
        guard=armasm.assemble(HERE.parent/'fp_usb_shell/asm/fpl_ui_guard.S',
                              ['RUNTIME_ARGS=1','PRODUCER_TRACE=1'])
        symbols['guard']=len(code)
        code+=guard
        if len(code)&3 or len(code)>0x3000:
            raise ValueError('producer text exceeds separate owned reservation')
        return SimpleNamespace(code=code, functions=symbols)
