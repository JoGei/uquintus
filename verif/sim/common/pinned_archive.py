"""Checksum-pinned public source archives, cached without Git submodules."""
import hashlib
import json
from pathlib import Path
import re
import shutil
import tarfile
import tempfile
from urllib.request import urlopen


def load_lock(path):
    lock = json.loads(path.read_text())
    if (lock.get('schema_version') != 1 or
            not re.fullmatch(r'[a-z][a-z0-9_-]*', lock.get('name', '')) or
            not re.fullmatch(r'[0-9a-f]{40}', lock.get('revision', '')) or
            not re.fullmatch(r'[0-9a-f]{64}', lock.get('archive_sha256', '')) or
            not lock.get('archive_url', '').startswith('https://')):
        raise ValueError('invalid pinned archive lock')
    return lock


def verify_sources(directory, lock):
    inventory_path = directory / '.uqu-source.json'
    if not inventory_path.is_file():
        raise ValueError('pinned source cache missing; run make benchmark-fetch')
    inventory = json.loads(inventory_path.read_text())
    if inventory.get('lock') != lock:
        raise ValueError('source cache pin differs from lock.json')
    actual = {p.relative_to(directory).as_posix() for p in directory.rglob('*')
              if p.is_file() and p != inventory_path}
    if actual != set(inventory['files']):
        raise ValueError('cached source file set changed; refetch the pinned archive')
    for name, expected in inventory['files'].items():
        path = directory / name
        if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f'cached source changed: {name}; refetch the pinned archive')


def fetch(cache, lock, archive_path=None):
    cache.mkdir(parents=True, exist_ok=True)
    prefix = lock['name'] + '-' + lock['revision']
    destination = cache / prefix
    if destination.exists():
        verify_sources(destination, lock)
        return destination
    with tempfile.TemporaryDirectory(prefix='.' + lock['name'] + '-', dir=cache) as tmp:
        directory = Path(tmp)
        archive = directory / 'source.tar.gz'
        if archive_path:
            shutil.copyfile(archive_path, archive)
        else:
            with urlopen(lock['archive_url'], timeout=60) as response, archive.open('wb') as output:
                shutil.copyfileobj(response, output)
        if hashlib.sha256(archive.read_bytes()).hexdigest() != lock['archive_sha256']:
            raise ValueError('source archive SHA-256 does not match lock.json')
        with tarfile.open(archive, 'r:gz') as source:
            for member in source.getmembers():
                parts = Path(member.name).parts
                if (not parts or parts[0] != prefix or '..' in parts or
                        not (member.isdir() or member.isfile())):
                    raise ValueError('unexpected archive path/link')
            source.extractall(directory, filter='data')
        extracted = directory / prefix
        inventory = {p.relative_to(extracted).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                     for p in extracted.rglob('*') if p.is_file()}
        (extracted / '.uqu-source.json').write_text(json.dumps(
            {'lock': lock, 'files': inventory}, indent=2) + '\n')
        extracted.rename(destination)
    return destination
