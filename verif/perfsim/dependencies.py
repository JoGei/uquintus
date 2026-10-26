"""Pinned archive provisioning; no git checkout or submodule initialization."""
import hashlib
import json
from pathlib import Path
import re
import tarfile
import urllib.request


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_lock(path):
    data = json.loads(Path(path).read_text())
    if data.get('schema_version') != 1 or not isinstance(data.get('sources'), list):
        raise ValueError('invalid perfsim dependency lock')
    seen = set()
    for row in data['sources']:
        p = Path(row['path'])
        if p.is_absolute() or '..' in p.parts or row['path'] in seen:
            raise ValueError('unsafe/duplicate dependency path')
        seen.add(row['path'])
        for key, pattern in [('repository', r'[\w.-]+/[\w.-]+'),
                             ('revision', r'[0-9a-f]{40}'),
                             ('archive_sha256', r'[0-9a-f]{64}')]:
            if not re.fullmatch(pattern, row[key]):
                raise ValueError('invalid dependency '+key)
    if not data['sources'] or data['sources'][0]['path'] != '':
        raise ValueError('dependency lock must begin with the workspace')
    return data


def extract(archive, destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, 'r:gz') as stream:
        members = stream.getmembers()
        if not members or sum(m.size for m in members) > 512*1024*1024:
            raise ValueError('empty or oversized dependency archive')
        prefix = Path(members[0].name).parts[0]
        for member in members:
            p = Path(member.name)
            if p.is_absolute() or '..' in p.parts or p.parts[0] != prefix:
                raise ValueError('unsafe dependency archive member')
            if len(p.parts) > 1:
                member.name = str(Path(*p.parts[1:]))
                # Python's data filter also validates symlink/hardlink targets.
                stream.extract(member, destination, filter='data')


def fetch(lock, root, archives, offline=False):
    root, archives = Path(root), Path(archives)
    archives.mkdir(parents=True, exist_ok=True)
    for row in lock['sources']:
        archive = archives/(row['repository'].replace('/', '-')+'-'+row['revision']+'.tar.gz')
        if not archive.exists():
            if offline:
                raise ValueError('missing offline dependency archive: '+str(archive))
            url = f"https://codeload.github.com/{row['repository']}/tar.gz/{row['revision']}"
            temporary = archive.with_suffix('.download')
            try:
                with urllib.request.urlopen(url, timeout=90) as src, temporary.open('wb') as dst:
                    while chunk := src.read(1024*1024):
                        dst.write(chunk)
                if digest(temporary) != row['archive_sha256']:
                    raise ValueError('dependency archive checksum mismatch: '+str(archive))
                temporary.replace(archive)
            finally:
                temporary.unlink(missing_ok=True)
        if digest(archive) != row['archive_sha256']:
            raise ValueError('dependency archive checksum mismatch: '+str(archive))
        dest = root/row['path']
        marker = dest/'.uqu-source.json'
        if not marker.exists() or json.loads(marker.read_text()) != row:
            extract(archive, dest)
            marker.write_text(json.dumps(row, indent=2)+'\n')
        print('Dependency:', row['repository'], row['revision'], flush=True)


def check_sources(lock, root):
    for row in lock['sources']:
        marker = Path(root)/row['path']/'.uqu-source.json'
        if not marker.exists() or json.loads(marker.read_text()) != row:
            raise ValueError('run make perfsim-fetch to provide pinned dependency '+row['repository'])
