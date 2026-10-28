#!/usr/bin/env python3
"""Install/remove ONE candidate in an owned rootfs inside unprivileged bwrap."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parent


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--distribution',choices=['debian','devuan'],required=True)
    parser.add_argument('--rootfs',type=Path,required=True)
    parser.add_argument('--deb',type=Path,required=True)
    args=parser.parse_args()
    rootfs=args.rootfs.resolve();deb=args.deb.resolve()
    assert rootfs.is_relative_to((ROOT/'.tmp').resolve()) and deb.is_relative_to((ROOT/'.tmp').resolve())
    lock=json.loads((ROOT/'packaging/ci-lock.json').read_text())
    assert (rootfs/'.gpt2codex-alpha-isolated').read_text().strip()==lock['images'][args.distribution]['image']
    assert deb.name=='gpt2codex_0.1.0~alpha1_amd64.deb'
    scratch=Path(tempfile.mkdtemp(prefix='alpha-runtime-',dir=ROOT/'.tmp')).resolve()
    logs=Path(tempfile.mkdtemp(prefix='alpha-runtime-'+args.distribution+'-',dir=ROOT/'.log')).resolve()
    subprocess.run(['python3',str(ROOT/'gpt2codex-alpha.py'),'stage','--destination',str(scratch/'source')],check=True)
    # No host root, HOME, /tmp, session state or default sockets are mounted.
    command=['bwrap','--die-with-parent','--unshare-all','--share-net','--uid','0','--gid','0',
             '--bind',str(rootfs),'/', '--proc','/proc','--dev','/dev','--tmpfs','/run',
             '--ro-bind','/etc/resolv.conf','/etc/resolv.conf','--ro-bind',str(scratch/'source'),'/src',
             '--ro-bind',str(deb),'/input/'+deb.name,'--bind',str(logs),'/out','--chdir','/',
             '--setenv','G2C_ALPHA_CONTAINER','1','/bin/sh','/src/gpt2codex-alpha-container.sh','smoke',args.distribution]
    env={'PATH':os.defpath,'LANG':'C.UTF-8','LC_ALL':'C.UTF-8'}
    print('RUNTIME_LOGS='+str(logs),flush=True)
    with (logs/'smoke.log').open('w') as out:
        result=subprocess.run(command,env=env,stdout=out,stderr=subprocess.STDOUT,timeout=900)
    if result.returncode:
        (logs/'unverified.json').write_text(json.dumps({'status':'NOT VERIFIED','distribution':args.distribution,'reason':'isolated smoke failed; see smoke.log','exit_code':result.returncode},indent=2)+'\n')
        raise SystemExit(result.returncode)
    print('CLEAN_INSTALL=PASS distribution='+args.distribution+' evidence='+str(logs))


if __name__=='__main__':main()
