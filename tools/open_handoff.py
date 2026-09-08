"""Authenticate and decrypt a preserved-game ZIP; never extract or resume it."""
import argparse
import base64
from pathlib import Path

MAGIC = b'EDH-HANDOFF-AESGCM-1\n'
MAX_BYTES = 256 * 1024 * 1024


def decrypt(source, key_file, output):
    if output.exists():
        raise ValueError('Output already exists; choose a new ZIP path.')
    if source.stat().st_size > MAX_BYTES:
        raise ValueError('Archive exceeds the bounded decryption limit.')
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    key = base64.b64decode(key_file.read_bytes().strip(), validate=True)
    if len(key) != 32:
        raise ValueError('A 256-bit handoff key is required.')
    data = source.read_bytes()
    if not data.startswith(MAGIC) or len(data) < len(MAGIC) + 28:
        raise ValueError('Unknown or incomplete handoff archive.')
    offset = len(MAGIC)
    plain = AESGCM(key).decrypt(data[offset:offset + 12], data[offset + 12:], MAGIC)
    with output.open('xb') as stream:
        stream.write(plain)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path)
    parser.add_argument('--key-file', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        decrypt(args.archive, args.key_file, args.output)
    except ImportError:
        parser.exit(1, 'Install the optional decryption dependency: python -m pip install cryptography\n')
    except Exception as error:
        parser.exit(1, 'Decryption failed (' + type(error).__name__ + '); verify the archive, private key and output path.\n')
    print('Authenticated ZIP written. It remains paused and has not been imported or extracted.')


if __name__ == '__main__':
    main()
