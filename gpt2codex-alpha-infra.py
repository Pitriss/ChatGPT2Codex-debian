#!/usr/bin/env python3
"""Explicitly refresh public image/action pins; never log registry tokens."""
import hashlib
import argparse
import io
import json
from pathlib import Path
import os
import re
import subprocess
import tempfile
import lzma
import tarfile
import urllib.parse
import urllib.request


def get(url, headers=None):
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers or {}), timeout=40) as response:
        return response.read()


def pull_rootfs(distribution, destination):
    assert not destination.exists(), 'refuse replacing any root filesystem'
    lock=json.loads(Path('packaging/ci-lock.json').read_text())
    image=lock['images'][distribution]['image']
    repo,digest=image.split('@')
    if '/' not in repo: repo='library/'+repo
    query=urllib.parse.urlencode({'service':'registry.docker.io','scope':f'repository:{repo}:pull'})
    token=json.loads(get('https://auth.docker.io/token?'+query))['token']
    headers={'Authorization':'Bearer '+token,'Accept':'application/vnd.oci.image.index.v1+json, application/vnd.docker.distribution.manifest.list.v2+json, application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json'}
    def blob(path, expected):
        raw=get(f'https://registry-1.docker.io/v2/{repo}/'+path)
        assert 'sha256:'+hashlib.sha256(raw).hexdigest()==expected
        return raw
    raw=get(f'https://registry-1.docker.io/v2/{repo}/manifests/{digest}',headers)
    assert 'sha256:'+hashlib.sha256(raw).hexdigest()==digest
    manifest=json.loads(raw)
    if 'manifests' in manifest:
        entry=next(x for x in manifest['manifests'] if x['platform'].get('os')=='linux' and x['platform'].get('architecture')=='amd64')
        raw=get(f'https://registry-1.docker.io/v2/{repo}/manifests/'+entry['digest'],headers)
        assert 'sha256:'+hashlib.sha256(raw).hexdigest()==entry['digest']
        manifest=json.loads(raw)
    config_raw=get(f'https://registry-1.docker.io/v2/{repo}/blobs/'+manifest['config']['digest'],headers)
    assert 'sha256:'+hashlib.sha256(config_raw).hexdigest()==manifest['config']['digest']
    assert json.loads(config_raw)['architecture']=='amd64'
    destination.mkdir(parents=True)
    for entry in manifest['layers']:
        raw=get(f'https://registry-1.docker.io/v2/{repo}/blobs/'+entry['digest'],headers)
        assert 'sha256:'+hashlib.sha256(raw).hexdigest()==entry['digest']
        with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
            for member in archive:
                assert not Path(member.name).name.startswith('.wh.'), 'unsupported OCI whiteout; refuse ambiguous extraction'
                if member.isdev() or member.isfifo(): continue
                if member.issym() and member.linkname.startswith('/'):
                    # Preserve in-container meaning, without an absolute link
                    # that could escape the destination during extraction.
                    target=destination/member.linkname.lstrip('/')
                    member.linkname=os.path.relpath(target,(destination/member.name).parent)
                archive.extract(member,destination,filter='data')
        print(distribution,'verified layer',entry['digest'],len(raw),flush=True)
    (destination/'.gpt2codex-alpha-isolated').write_text(image+'\n')
    print('ROOTFS='+str(destination.resolve()),flush=True)


def lint_tool(destination):
    assert not destination.exists()
    release=json.loads(get('https://api.github.com/repos/rhysd/actionlint/releases/latest'))
    assets={a['name']:a for a in release['assets']}
    name=next(n for n in assets if n.endswith('_linux_amd64.tar.gz'))
    checks=next(n for n in assets if n.endswith('_checksums.txt'))
    checksum=get(assets[checks]['browser_download_url']).decode()
    expected=next(line.split()[0] for line in checksum.splitlines() if line.split()[-1]==name)
    raw=get(assets[name]['browser_download_url'])
    assert hashlib.sha256(raw).hexdigest()==expected
    destination.mkdir(parents=True)
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        for member in archive:
            if member.name in {'actionlint','LICENSE'}:archive.extract(member,destination,filter='data')
    print('ACTIONLINT='+release['tag_name']+' SHA256='+expected+' PATH='+str(destination.resolve()))


def lintian_tool(destination):
    assert not destination.exists()
    plan=subprocess.check_output(['apt-get','-s','--no-install-recommends','install','lintian'],text=True,stderr=subprocess.DEVNULL)
    packages=re.findall(r'^Inst (\S+)(?: \[[^]]+\])? \((\S+)',plan,re.M)
    assert any(name=='lintian' for name,_ in packages)
    destination.mkdir(parents=True)
    records=[]
    for name,version in packages:
        metadata=subprocess.check_output(['apt-cache','show',name+'='+version],text=True)
        fields=dict(line.split(': ',1) for line in metadata.splitlines() if ': ' in line and not line.startswith(' '))
        assert fields['Filename'].startswith('pool/')
        raw=get('https://deb.debian.org/debian/'+fields['Filename'])
        assert hashlib.sha256(raw).hexdigest()==fields['SHA256']
        archive=destination/Path(fields['Filename']).name
        archive.write_bytes(raw)
        subprocess.run(['dpkg-deb','-x',str(archive),str(destination)],check=True)
        records.append({'name':name,'version':version,'sha256':fields['SHA256']})
    (destination/'tool-packages.json').write_text(json.dumps(records,indent=2)+'\n')
    print('LINTIAN_EXTRACTED='+str(destination.resolve())+' PACKAGES='+str(len(records)),flush=True)


def devuan_metadata(destination, keyring):
    base='https://pkgmaster.devuan.org/merged/dists/excalibur/'
    release=get(base+'InRelease')
    with tempfile.TemporaryDirectory(prefix='alpha-index-',dir=Path('.tmp')) as temp:
        signature=Path(temp)/'InRelease';signature.write_bytes(release)
        subprocess.run(['gpgv','--homedir',str(Path(temp).resolve()),'--keyring',str(keyring.resolve()),str(signature)],check=True)
    matches=re.findall(rb'^ ([0-9a-f]{64})\s+([0-9]+)\s+main/binary-amd64/Packages.xz$',release,re.M)
    assert len(matches)==1
    data=get(base+'main/binary-amd64/Packages.xz')
    assert len(data)==int(matches[0][1]) and hashlib.sha256(data).hexdigest()==matches[0][0].decode()
    wanted={'libc6','libgcc-s1','libkf6configcore6','libkf6coreaddons6','libkf6parts6','libkf6xmlgui6','libqt6core6t64',
            'libqt6gui6','libqt6widgets6','libqtermwidget6-2','libstdc++6','git','screen','konsole-kpart','qt6-svg-plugins',
            'breeze-icon-theme','libsystemd0','libelogind0'}
    packages={}
    for block in lzma.decompress(data).decode().split('\n\n'):
        fields=dict(line.split(': ',1) for line in block.splitlines() if ': ' in line and not line.startswith(' '))
        if fields.get('Package') in wanted:
            packages[fields['Package']]={key:fields.get(key,'') for key in ['Version','Architecture','Depends','Provides']}
    destination.write_text(json.dumps({'release_sha256':hashlib.sha256(release).hexdigest(),'index_sha256':hashlib.sha256(data).hexdigest(),
                           'signature':'gpgv verified using keyring from pinned official Devuan rootfs',
                           'packages':packages,'scope':'metadata only; not an installation or runtime PASS'},indent=2)+'\n')
    print('DEVUAN_METADATA='+str(destination)+' PACKAGES='+str(len(packages)))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rootfs',choices=['debian','devuan'])
    parser.add_argument('--actionlint',action='store_true')
    parser.add_argument('--lintian',action='store_true')
    parser.add_argument('--devuan-metadata',action='store_true')
    parser.add_argument('--keyring',type=Path)
    parser.add_argument('--destination',type=Path)
    args=parser.parse_args()
    if args.rootfs:
        assert args.destination;pull_rootfs(args.rootfs,args.destination);return
    if args.actionlint:
        assert args.destination;lint_tool(args.destination);return
    if args.lintian:
        assert args.destination;lintian_tool(args.destination);return
    if args.devuan_metadata:
        assert args.destination and args.keyring;devuan_metadata(args.destination,args.keyring);return
    images = {}
    for key, repo, tag in [('debian', 'library/debian', 'trixie-slim'),
                          ('devuan', 'devuan/devuan', 'excalibur'),
                          ('binfmt', 'tonistiigi/binfmt', 'qemu-v9.2.2')]:
        query = urllib.parse.urlencode({'service': 'registry.docker.io', 'scope': f'repository:{repo}:pull'})
        token = json.loads(get('https://auth.docker.io/token?' + query))['token']
        raw = get(f'https://registry-1.docker.io/v2/{repo}/manifests/{tag}',
                  {'Authorization': 'Bearer ' + token, 'Accept': 'application/vnd.oci.image.index.v1+json, application/vnd.docker.distribution.manifest.list.v2+json'})
        data = json.loads(raw)
        digest = 'sha256:' + hashlib.sha256(raw).hexdigest()
        platforms = {m['platform']['architecture'] + ('/' + m['platform']['variant'] if m['platform'].get('variant') else ''): m['digest']
                     for m in data.get('manifests', []) if m.get('platform', {}).get('os') == 'linux'}
        if not platforms:
            config = json.loads(get(f'https://registry-1.docker.io/v2/{repo}/blobs/' + data['config']['digest'], {'Authorization':'Bearer '+token}))
            assert config['os'] == 'linux'
            platforms[config['architecture']] = digest
        images[key] = {'image': repo.removeprefix('library/') + '@' + digest,
                       'tag_at_review': tag, 'platforms': platforms}
        print(key, images[key]['image'], sorted(platforms))
    actions = {}
    for repo, version in [('actions/checkout','v4.3.1'), ('actions/upload-artifact','v4.6.2'),
                          ('actions/download-artifact','v4.3.0'), ('docker/setup-qemu-action','v3.6.0')]:
        ref = json.loads(get(f'https://api.github.com/repos/{repo}/git/ref/tags/{version}', {'Accept':'application/vnd.github+json'}))['object']
        if ref['type'] == 'tag':
            ref = json.loads(get(ref['url']))['object']
        assert ref['type'] == 'commit'
        actions[repo] = {'version': version, 'commit': ref['sha']}
        print(repo, version, ref['sha'])
    Path('packaging').mkdir(exist_ok=True)
    release = get('https://snapshot.debian.org/archive/debian/20261027T000000Z/dists/trixie/Release')
    assert b'Codename: trixie\n' in release
    Path('packaging/ci-lock.json').write_text(json.dumps({'snapshot': '20261027T000000Z', 'images': images, 'actions': actions}, indent=2) + '\n')


if __name__ == '__main__':
    main()
